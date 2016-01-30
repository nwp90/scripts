#!/usr/bin/python3
#
# musicmaker.py - take Rhythmbox playlists and put converted
# versions of the files into desired directory structure for
# use with less capable player devices.
#
# requires:
# * python3
# * python3-defusedxml
# * python3-magic
# * rhythmbox in use
# * one or more converters, depending on intended use:
#   * avconv or ffmpeg + avconv compatibility frontend
#   * sox
#   ...and their dependencies (e.g. MP3 encoder)
#
# Originally intended to convert music files used on my desktop
# computer, which I store as .ogg or .flac, and convert them
# to .mp3 in directory structure suitable for use on NAS, USB
# sticks for use in car etc.
#
# Kind of like making mix tapes in the old days ;)
#
# Like many dirty hacks, it seems to be growing.
#
#
# Nick Phillips <nwp@zepler.net>
#

import argparse
import os
import sys
import pprint
import subprocess
import collections
import re
#import magic
from defusedxml.ElementTree import parse as xmlparse
from urllib.parse import urlparse, unquote, unquote_to_bytes

debug = 1

preference = ['sox', 'avconv']

handlers = {
    'sox': set([
            'mp3',
            'ogg',
            'oga',
            'flac',
            'wav',
            'aiff',
            'au',
            ]),
    'avconv': set([
            'mp3',
            'ogg',
            'oga',
            'flac',
            'wav',
            'aac',
            'aiff',
            'au',
            'm4a',
            ]),
    }
    
profiles = {
    'mp3': {
        'ext': 'mp3',
        'avconv': ['-id3v2_version', '3'],
        },
    'mp3-hiq': {
        'ext': 'mp3',
        'sox': ['-t', 'mp3', '-C', '0'],
        'avconv': ['-q:a', '0', '-id3v2_version', '3'],
        },
    'ogg': {
        'ext': 'ogg',
        },
}

extensions = set()
for handler in handlers.values():
    extensions.update(handler)

parser = argparse.ArgumentParser(description='Convert a playlist to desired format')
parser.add_argument('pl_names', metavar='playlist', type=str, nargs='+',
                    help='Names of playlists to copy/transcode')
parser.add_argument('-t', '--target', dest='target', type=str, required=True,
                    help='Target directory')
parser.add_argument('-s', '--single', dest='single', action='store_true', default=False,
                    help='Store all files within a single directory (target). '
                         'Takes precedence over -n option')
parser.add_argument('-n', '--named', dest='named', action='store_true', default=False,
                    help='Store all files within each playlist under a single '
                         'directory named as the playlist, under target')
parser.add_argument('-p', '--profile', dest='profile', type=str, default="mp3",
                    help='Target encoding profile')
parser.add_argument('-r', '--recode', dest='recode', action='store_true', default=False,
                    help='Recode files already using the target format')
parser.add_argument('-m', '--mangle', dest='mangle', action='store_true', default=False,
                    help='Mangle possibly-problematic characters in filenames '
                         '(e.g. if target is a FAT-based filesystem)')
parser.add_argument('-f', '--force', dest='force', action='store_true', default=False,
                    help='Continue working if target not empty')

args = parser.parse_args()
target = args.target

if not args.profile in profiles:
    # XXX - replace with exception?
    sys.stderr.write("ERROR: unknown profile {profile}\n".format(profile=args.profile))
    exit(1)

profile = profiles[args.profile]
pl_etree = xmlparse("{HOME}/.local/share/rhythmbox/playlists.xml".format_map(os.environ))
root = pl_etree.getroot()
playlists = root.findall(".//playlist[@type='static']")


def convert(item, converter, profile):
    print(b"Converting: " + b' => '.join([item['origin'], item['target']]))
    if converter == 'sox':
        cmd = ['sox', item['origin']]
        if 'sox' in profile:
            cmd.extend(profile['sox'])
        cmd.append(item['target'])
        subprocess.call(cmd)
    elif converter == 'avconv':
        cmd = ['avconv', '-i', item['origin']]
        if 'avconv' in profile:
            cmd.extend(profile['avconv'])
        cmd.append(item['target'])
        subprocess.call(cmd)
    else:
        sys.stderr.write("Unknown converter: {conv}\n".format(conv=converter))


toconvert = collections.OrderedDict()
for playlist in playlists:
    plname = playlist.attrib['name']
    if plname in args.pl_names:
        elements = playlist.findall("./location")
        for e in elements:
            (scheme, netloc, name) = urlparse(e.text)[0:3]
            if (scheme != 'file' or netloc != ''):
                sys.stderr.write("Ignoring {uri}.".format(uri=e.text))
                next
            name = unquote_to_bytes(name)
            # With -n, may want same file in multiple locations on target,
            # so use list.
            if not name in toconvert:
                toconvert[name] = []
            elif debug:
                sys.stderr.write("Current name: {}, playlist: {}\n".format(name, unquote_to_bytes(plname)))
            # Now avoid copy/converting twice to same destination
            # Not sure if debugging makes it harder or easier to read.
            for item in toconvert[name]:
                if debug:
                    sys.stderr.write("Comparing to name: {}, playlist: {}\n".format(item['origin'], item['playlist']))
                if item['origin'] == name:
                    if item['playlist'] == unquote_to_bytes(plname) or not args.named:
                        if debug:
                            sys.stderr.write("MATCHED.\n")
                        # Break past for loop's else
                        break
                    elif debug:
                        sys.stderr.write("No match (playlist).\n")
                elif debug:
                    sys.stderr.write("No match (name).\n")
            # This else is on the for loop. So we're only doing this if
            # we didn't match existing name & playlist (and therefore
            # take the break).
            else:
                toconvert[name].append({
                    'copy': False,
                    'uri': e.text,
                    'origin': name,
                    'playlist': unquote_to_bytes(plname),
                })

prefix = os.path.dirname(os.path.commonprefix(toconvert.keys()))

sys.stderr.write("Target is {target}.\n".format(target=target))
sys.stderr.write("Common prefix is {prefix}.\n".format(prefix=prefix))

# Implicitly test whether target is a directory
contents = os.listdir(target)
if contents and not args.force:
    # XXX - replace with exception?
    sys.stderr.write("Target directory '{target}' not empty.\n".format(target=target))
    exit(1)

for itemlist in toconvert.values():
    for item in itemlist:
        if args.single:
            mungename = os.path.basename(item['origin'])
        elif args.named:
            mungename = os.path.join(item['playlist'], os.path.basename(item['origin']))
        else:
            mungename = os.path.relpath(item['origin'], prefix)
        # Get rid of dodgy characters in filename if desired
        if args.mangle:
            mungename = re.sub(b'[^a-zA-Z0-9_/.]', b'_', mungename)
        # Build target path with original filename
        mungename = os.path.join(target.encode(), mungename)
        # Get dirname and filename
        (dirname, oldfilename) = os.path.split(mungename)
        if debug:
            sys.stderr.write("dirname: " + pprint.pformat(dirname) + "\n")
            sys.stderr.write("oldfilename: " + pprint.pformat(oldfilename) + "\n")
            sys.stderr.write("mungename: " + pprint.pformat(mungename) + "\n")
        item['dir'] = dirname
        # Switch or add appropriate extension
        filenameparts = oldfilename.rsplit(b'.', 1)
        sys.stderr.write("filenameparts is: " + pprint.pformat(filenameparts) + "\n")
        if len(filenameparts) == 2 and filenameparts[1].lower().decode('utf8') in extensions:
            item['extension'] = filenameparts[1].lower().decode('utf8')
            if debug:
                sys.stderr.write("newfilename is 0th part of oldfilename plus profile extension\n")
            newfilename = b'.'.join((filenameparts[0], profile['ext'].encode()))
            # While we're at it, set bool to indicate if we can just copy
            # file rather than transcoding. Decision based on old extension.
            # Yuk.
            if filenameparts[1].lower() == profile['ext'] and not args.recode:
                item['copy'] = True
        else:
            item['extension'] = None
            if debug:
                sys.stderr.write("newfilename is mungename plus profile extension\n")
            newfilename = b'.'.join((mungename, profile['ext'].encode()))
        # Put target back together again
        item['target'] = os.path.join(dirname, newfilename)

# Debug info
if debug:
    sys.stderr.write(pprint.pformat(toconvert) + "\n")

# Convert/copy ALL THE THINGS.
for itemlist in toconvert.values():
    for item in itemlist:
        if os.path.exists(item['target']):
            print("Skipping target (exists): {target}".format(target=item['target']))
            continue
        if not os.path.isdir(item['dir']):
            print("Creating directory: {dirname}".format(dirname=item['dir']))
            subprocess.call(['mkdir', '-p', item['dir']])
        if item['copy']:
            cmd = ['cp', item['origin'], item['target']]
            print("Copying: " + ' '.join(cmd))
            subprocess.call(cmd)
        else:
            for converter in preference:
                if item['extension'] in handlers[converter]:
                    convert(item, converter, profile)
                    break
            else:
                sys.stderr.write('No handler for extension: {ext}\n'.format(ext=item['extension']))
