#!/usr/bin/python

"""
This script is horrible. It barely functions.


But it does function.
"""


import subprocess
import plistlib
import tempfile
import os.path
import os
import requests
from json import dumps
import sys

munkirepo = os.path.join(os.environ["CIRCLE_WORKING_DIRECTORY"], "macaduck19-munki_repo")


if os.path.isfile("/usr/local/bin/git"):
    git = "/usr/local/bin/git"
else:
    git = "/usr/bin/git"

recipes = [
    "GoogleChrome.munki.recipe"
]

# from http://stackoverflow.com/posts/3326559/revisions

from os import kill
from signal import alarm, signal, SIGALRM, SIGKILL
from subprocess import PIPE, Popen


def run(args, cwd=None, shell=False, kill_tree=True, timeout=-1, env=None):
    '''
    Run a command with a timeout after which it will be forcibly
    killed.
    '''
    class Alarm(Exception):
        pass

    def alarm_handler(signum, frame):
        raise Alarm
    p = Popen(args, shell=shell, cwd=cwd, stdout=PIPE, stderr=PIPE, env=env)
    if timeout != -1:
        signal(SIGALRM, alarm_handler)
        alarm(timeout)
    try:
        stdout, stderr = p.communicate()
        if timeout != -1:
            alarm(0)
    except Alarm:
        pids = [p.pid]
        if kill_tree:
            pids.extend(get_process_children(p.pid))
        for pid in pids:
            # process might have died before getting to this line
            # so wrap to avoid OSError: no such process
            try:
                kill(pid, SIGKILL)
            except OSError:
                pass
        return -9, '', ''
    return p.returncode, stdout, stderr


def get_process_children(pid):
    p = Popen('ps --no-headers -o pid --ppid %d' % pid, shell=True,
              stdout=PIPE, stderr=PIPE)
    stdout, stderr = p.communicate()
    return [int(p) for p in stdout.split()]

def create_pull_request(reponame, head, base, title, body, credentials):
    r = requests.post(
        'https://api.github.com/repos/' +
        reponame +
        '/pulls',
        auth=credentials,
        data=dumps(
            {
                'head': head,
                'base': base,
                'title': title,
                'body': body}))
    return r.json()


credentials = ('grahamgilbert', os.environ["github_api"])
repo = 'grahamgilbert/macaduck19-munki_repo'

# just for my sanity
subprocess.call([git, '-C', munkirepo, 'fetch', 'origin'])
subprocess.call([git, '-C', munkirepo, 'checkout', 'master'])
subprocess.call([git, '-C', munkirepo, 'clean', '-fd'])
subprocess.call([git, '-C', munkirepo, 'reset', '--hard', 'origin/master'])

for recipe in recipes:

    print 'Running recipe ' + recipe
    # insanity
    subprocess.call([git, '-C', munkirepo, 'fetch', 'origin'])
    subprocess.call([git, '-C', munkirepo, 'checkout', 'master'])
    subprocess.call([git, '-C', munkirepo, 'reset', '--hard', 'origin/master'])

    plist = tempfile.mkstemp(suffix='.plist')[1]
    print run(['/usr/local/bin/autopkg', 'run', recipe,
               '--report-plist', plist, '-k', 'MUNKI_REPO=' + munkirepo], timeout=900)[1]
    print run(['/usr/sbin/diskutil', 'eject', '/dev/disk2'], timeout=10)[1]

    reportplist = plistlib.readPlist(plist)

    try:
        if 'munki_importer_summary_result' in reportplist['summary_results']:
            report = reportplist['summary_results'][
                'munki_importer_summary_result']['data_rows'][0]
            name = report['name']
            version = report['version']
            commit = name + '-' + version

            # we cant have spaces in branch names
            branchname = commit.replace(" ", "")

            subprocess.call(['/usr/local/bin/autopkg',
                             'run',
                             '-k',
                             'force_rebuild=YES',
                             'MakeCatalogs.munki',
                             '-k',
                             'MUNKI_REPO=' + munkirepo])

            makebranch = True

            # previously used 'git branch -r' but changed so if the local branch is deleted
            # it can actually work
            branches = subprocess.Popen(
                [git, '-C', munkirepo, 'branch', '-v'], stdout=subprocess.PIPE)

            for branch in branches.stdout.readlines():
                if branchname in branch:
                    makebranch = False

            if makebranch:
                subprocess.call(
                    [git, '-C', munkirepo, 'checkout', '-b', branchname])
                subprocess.call([git, '-C', munkirepo, 'add', munkirepo])
                subprocess.call([git, '-C', munkirepo, 'commit',
                                 '-m', commit])
                subprocess.call(
                    [git, '-C', munkirepo, 'push', 'origin', branchname])
                print create_pull_request(repo, branchname, 'master', commit, dumps(report), credentials)
            else:
                subprocess.call([git, '-C', munkirepo, 'clean', '-fd'])
                subprocess.call([git, '-C', munkirepo, 'reset',
                                 '--hard', 'origin/master'])
    except Exception as e:
        print(e)
        sys.exit(1)
