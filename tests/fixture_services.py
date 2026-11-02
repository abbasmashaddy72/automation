"""Explicit systemd command availability for mocked user-service contracts only."""
from unittest.mock import patch
import services


def assume_systemctl(case):
    native=services.shutil.which
    fixture=patch.object(services.shutil,'which',side_effect=lambda command,*args,**kwargs:
        '/fixture/systemctl' if command=='systemctl' else native(command,*args,**kwargs))
    fixture.start();case.addCleanup(fixture.stop)
