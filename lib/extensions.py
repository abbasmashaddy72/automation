"""Opt-in declarative provider manifests; no executable plugin hooks or repos."""
from __future__ import annotations
import re
from pathlib import Path
import workflows

FAMILIES = ('arch','debian','fedora','rhel','opensuse','alpine')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,95}\Z')


def read_provider(path):
    manifest=workflows.read_json(Path(path), max_size=65536)
    if not isinstance(manifest,dict) or set(manifest)!= {'schema','id','packages'} or manifest['schema']!=1:
        raise ValueError('Unsupported provider schema')
    if not isinstance(manifest['id'],str) or not NAME.fullmatch(manifest['id']): raise ValueError('Invalid provider ID')
    packages=manifest['packages']
    if not isinstance(packages,dict) or not 1<=len(packages)<=150:raise ValueError('Invalid provider packages')
    for label, mapping in packages.items():
        if not isinstance(label,str) or not NAME.fullmatch(label) or not isinstance(mapping,dict) or not mapping or set(mapping)-set(FAMILIES):
            raise ValueError('Invalid provider package mapping')
        for family, package in mapping.items():
            if not isinstance(package,str) or not NAME.fullmatch(package) or package=='lerd' or package.startswith('ai-'):
                raise ValueError(f'Invalid package name for {family}')
    return manifest


def resolve(manifest, selections, family):
    unknown=set(selections)-set(manifest['packages'])
    if unknown:raise ValueError('Unknown provider selections: '+', '.join(sorted(unknown)))
    unavailable=[x for x in selections if family not in manifest['packages'][x]]
    if unavailable:raise ValueError('Provider lacks mapping for family: '+', '.join(unavailable))
    return [manifest['packages'][x][family] for x in selections]
