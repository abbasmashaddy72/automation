"""Official installer redirects remain restricted to Ollama's release identity."""
from argparse import Namespace
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'ai'))
import portable

ASSET='https://release-assets.githubusercontent.com/github-production-release-asset/658928958/3290df5e-1966-468a-ae78-876d00e09c02?fixture=token'

class InstallerVerification(unittest.TestCase):
    def test_only_official_release_identity_is_accepted(self):
        for url in ('https://ollama.com/install.sh','https://github.com/ollama/ollama/releases/latest/download/install.sh','https://github.com/ollama/ollama/releases/download/v0.40.13/install.sh',ASSET):
            self.assertTrue(portable.installer_destination(url))
        for url in ('http://ollama.com/install.sh','https://evil.example/install.sh','https://github.com/another/project/releases/download/v1/install.sh',ASSET.replace('/658928958/','/123/'),'https://user:secret@ollama.com/install.sh','https://ollama.com:444/install.sh','https://github.com/ollama/ollama/releases/latest/download/install.sh?token=secret'):
            self.assertFalse(portable.installer_destination(url))
    def test_untrusted_intermediate_hop_is_refused(self):
        handler=portable.InstallerRedirect()
        with self.assertRaises(ValueError):handler.redirect_request(portable.urllib.request.Request('https://ollama.com/install.sh'),None,302,'Found',{},'https://evil.example/redirect-back-to-ollama')
    def test_redirect_hop_limit_is_bounded(self):
        handler=portable.InstallerRedirect();handler.hops=5
        with self.assertRaises(ValueError):handler.redirect_request(portable.urllib.request.Request('https://ollama.com/install.sh'),None,302,'Found',{},'https://github.com/ollama/ollama/releases/latest/download/install.sh')
    def test_signed_release_payload_is_bounded_without_logging_its_token(self):
        response=MagicMock();response.__enter__.return_value=response;response.url=ASSET;response.read.return_value=b'#!/bin/sh\n# ollama fixture\ntrue\n'
        with patch.object(portable.urllib.request,'build_opener') as build:
            build.return_value.open.return_value=response
            self.assertTrue(portable.installer_payload().startswith(b'#!'))
        response.read.assert_called_once_with(500001)
    def test_untrusted_final_response_is_not_read(self):
        response=MagicMock();response.__enter__.return_value=response;response.url='https://evil.example/script'
        with patch.object(portable.urllib.request,'build_opener') as build:
            build.return_value.open.return_value=response
            with self.assertRaises(ValueError):portable.installer_payload()
        response.read.assert_not_called()
    def test_invalid_shell_is_never_executed(self):
        args=Namespace(action='install',yes=True,dry_run=False)
        with patch.object(portable.shutil,'which',return_value=None),patch.object(portable,'installer_payload',return_value=b'#!/bin/sh\n# ollama\nif\n'),patch.object(portable,'command') as execute,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):portable.install_ollama(args)
        execute.assert_not_called()
