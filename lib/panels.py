"""Cinnamon grouped-window-list and XFCE launcher adapters; no session restart."""
from __future__ import annotations
import ast
import configparser
import json
import os
from pathlib import Path
import re
import subprocess
import filesystem as production


def read(path):
    path=production.checked(path);st=path.stat()
    if not path.is_file() or st.st_uid!=os.getuid() or st.st_nlink!=1 or st.st_size>262144:raise ValueError('Unsafe or oversized panel configuration')
    return path.read_text()


def cinnamon_path():
    import desktop
    values=ast.literal_eval(desktop.gsettings('get','org.cinnamon','enabled-applets').removeprefix('@as '))
    if not isinstance(values,list) or any(not isinstance(item,str) for item in values):raise ValueError('Invalid Cinnamon applet list')
    matches=[item.split(':')[-1] for item in values if ':grouped-window-list@cinnamon.org:' in item]
    if len(matches)!=1 or not re.fullmatch('[0-9]{1,8}',matches[0]):raise ValueError('Exactly one active Cinnamon grouped-window-list is required')
    base=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'cinnamon/spices/grouped-window-list@cinnamon.org'
    modern=base/(matches[0]+'.json')
    old=Path.home()/'.cinnamon/configs/grouped-window-list@cinnamon.org'/(matches[0]+'.json')
    return matches[0],production.checked(modern if modern.exists() or modern.is_symlink() else old)


def xfconf(*args,missing=False):
    result=subprocess.run(['xfconf-query','--channel','xfce4-panel',*args],capture_output=True,text=True,timeout=10,
        env={**os.environ,'LC_ALL':'C'})
    if missing and result.returncode==1 and 'does not exist' in result.stderr:return ''
    if result.returncode or len(result.stdout)>1048576:raise ValueError('XFCE configuration query failed')
    return result.stdout.strip()


def array(value):
    if value.startswith('Value is an array'):
        return [line.strip() for line in value.splitlines()[1:] if line.strip()]
    return [value] if value else []


def xfce_plugin():
    values=xfconf('--list','--verbose')
    candidates=re.findall(r'^/plugins/plugin-([0-9]+)\s+launcher\s*$',values,re.M)
    active=set()
    for panel in re.findall(r'^/panels/panel-([0-9]+)/plugin-ids\s',values,re.M):
        active.update(array(xfconf('--property','/panels/panel-'+panel+'/plugin-ids')))
    candidates=[value for value in candidates if value in active]
    if len(candidates)!=1:raise ValueError('Exactly one active XFCE Launcher group is required; multi-launcher panels need explicit manual selection')
    return candidates[0]


def xfce_directory(plugin):
    if not re.fullmatch('[0-9]{1,8}',plugin):raise ValueError('Invalid XFCE plugin identity')
    return production.checked(Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'xfce4/panel'/('launcher-'+plugin))


def snapshot(adapter):
    if adapter=='cinnamon':
        instance,path=cinnamon_path();text=read(path)
        data=json.loads(text,object_pairs_hook=production.unique)
        if not isinstance(data,dict) or not isinstance(data.get('pinned-apps'),dict):raise ValueError('Invalid Cinnamon panel schema')
        values=data['pinned-apps'].get('value')
        if not isinstance(values,list) or len(values)>200 or any(not isinstance(x,str) for x in values):raise ValueError('Invalid Cinnamon pinned-apps data')
        return {'kind':adapter,'instance':instance,'text':text}
    plugin=xfce_plugin();folder=xfce_directory(plugin)
    items=array(xfconf('--property','/plugins/plugin-'+plugin+'/items',missing=True))
    if len(items)>200 or any(any(ord(c)<32 for c in item) for item in items):raise ValueError('Invalid XFCE item list')
    files={}
    if folder.exists():
        if not folder.is_dir() or folder.stat().st_uid!=os.getuid():raise ValueError('Unowned XFCE launcher directory')
        for file in folder.glob('*.desktop'):
            if len(files)>=100:raise ValueError('Too many XFCE launcher files')
            files[file.name]=read(file)
    return {'kind':adapter,'plugin':plugin,'items':items,'files':files}


def application_file(name):
    bases=[Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))]
    bases += [Path(x) for x in os.environ.get('XDG_DATA_DIRS','/usr/local/share:/usr/share').split(':') if x.startswith('/')]
    for base in bases:
        path=base/'applications'/name
        if path.is_file() and path.stat().st_size<=262144:return path
    raise ValueError('Selected .desktop file is unavailable')


def update(before,names):
    after=json.loads(json.dumps(before))
    if before['kind']=='cinnamon':
        data=json.loads(before['text'],object_pairs_hook=production.unique)
        original=data['pinned-apps']['value']
        values=list(dict.fromkeys([*original,*names]))
        if values==original:return before
        data['pinned-apps']['value']=values;after['text']=json.dumps(data,indent=2)+'\n';return after
    for name in names:
        source=application_file(name);uri=source.absolute().as_uri()
        existing=any(item in before['items'] for item in (name,uri,str(source.absolute())))
        for text in before['files'].values():
            config=configparser.ConfigParser(interpolation=None,strict=False)
            config.optionxform=str
            config.read_string(text)
            if config.get('Desktop Entry','X-XFCE-Source',fallback='')==uri:existing=True
        if existing:continue
        filename='automation-'+name
        text=source.read_text()
        config=configparser.ConfigParser(interpolation=None,strict=False);config.optionxform=str;config.read_string(text)
        if not config.has_section('Desktop Entry') or config.get('Desktop Entry','Type',fallback='Application')!='Application':raise ValueError('Expected an application desktop entry')
        config.set('Desktop Entry','X-XFCE-Source',uri)
        import io
        stream=io.StringIO();config.write(stream);text=stream.getvalue()
        if filename in after['files'] and after['files'][filename]!=text:raise ValueError('Existing launcher file conflicts; no overwrite')
        after['files'][filename]=text
        if filename not in after['items']:after['items'].append(filename)
    return after


def write(value):
    adapter=value['kind'];before=snapshot(adapter)
    if adapter=='cinnamon':
        instance,path=cinnamon_path()
        if instance!=value.get('instance'):raise ValueError('Active Cinnamon applet changed')
        # Validate before replacing, including unrelated JSON fields preserved by
        # update(). No desktop code or plugin hook is executed.
        data=json.loads(value['text'],object_pairs_hook=production.unique)
        if not isinstance(data.get('pinned-apps',{}).get('value'),list):raise ValueError('Invalid Cinnamon restore data')
        production.atomic(path,value['text'].encode(),path.stat().st_mode&0o777);return
    if before['plugin']!=value.get('plugin'):raise ValueError('Active XFCE launcher changed')
    folder=xfce_directory(value['plugin']);created=[]
    removed=set(before['files'])-set(value['files'])
    if any(not name.startswith('automation-') for name in removed):raise ValueError('Refusing to remove unrelated launcher files')
    for name,text in value['files'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.desktop',name):raise ValueError('Invalid launcher file name')
        if name in before['files'] and before['files'][name]!=text:raise ValueError('Launcher contents changed; no overwrite')
    def set_items(items):
        if not items:
            xfconf('--property','/plugins/plugin-'+value['plugin']+'/items','--reset');return
        args=['--property','/plugins/plugin-'+value['plugin']+'/items','--force-array','--create']
        for item in items:args+=['--type','string','--set',item]
        xfconf(*args)
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        for name,text in value['files'].items():
            if name in before['files']:continue
            fd=os.open(folder/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
            with os.fdopen(fd,'w') as stream:stream.write(text)
            created.append(name)
        set_items(value['items'])
        for name in removed:
            path=folder/name
            if path.exists():
                if read(path)!=before['files'][name]:raise ValueError('Launcher edited during restore; preserving it')
                path.unlink()
    except BaseException:
        observed=array(xfconf('--property','/plugins/plugin-'+value['plugin']+'/items'))
        if observed==value['items'] and before['items']:set_items(before['items'])
        for name in created:
            path=folder/name
            if path.exists() and name not in observed and read(path)==value['files'][name]:path.unlink()
        raise
