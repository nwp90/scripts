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
import unicodedata
#import magic
from defusedxml.ElementTree import parse as xmlparse
from urllib.parse import urlparse, unquote, unquote_to_bytes

DEBUG = 1

preference = ['sox', 'avconv', 'ffmpeg']

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
    'ffmpeg': set([
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

class UnknownConverter(Exception):
    pass

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
parser.add_argument('-x', '--translatefrom', dest='translatefrom', type=str, default=None,
                    help='Path translation original')
parser.add_argument('-y', '--translateto', dest='translateto', type=str, default=None,
                    help='Path translation modified')
parser.add_argument('-o', '--origin', dest='origin', type=str, default=None,
                    help='Origin of playlists (file or dir path depending on playlist type)')
parser.add_argument('-S', '--synofix', dest='synofix', action='store_true', default=False,
                    help='Mangle paths from m3u files to work around bug in Synology AudioStation')
#parser.add_argument('-i', '--input-encoding', dest='iconvin', type=str, default='utf-8',
#                    help='Input (playlist) character encoding')
#parser.add_argument('-j', '--output-encoding', dest='iconvout', type=str, default='utf-8',
#                    help='Output (file naming) character encoding')


args = parser.parse_args()
target = args.target

if not args.profile in profiles:
    # XXX - replace with exception?
    sys.stderr.write("ERROR: unknown profile {profile}\n".format(profile=args.profile))
    exit(1)

profile = profiles[args.profile]

# xor
if (args.translatefrom is None) != (args.translateto is None):
    sys.stderr.write("ERROR: neither or both of translateto and translatefrom must be set\n")
    exit(1)

def debug(level, text):
    global DEBUG
    if DEBUG >= level:
        sys.stderr.write('%s\n' % text)


def dformat(level, *args, **kwargs):
    global DEBUG
    if DEBUG >= level:
        return pprint.pformat(*args, **kwargs)
    return ""


def convert(item, converter, profile):
    print(b"Converting: " + b' => '.join([item['origin'], item['target']]))
    if 0:
        cmd = ['echo', item['origin'], item['target']]
        return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if converter == 'sox':
        cmd = ['sox', item['origin']]
        if 'sox' in profile:
            cmd.extend(profile['sox'])
        cmd.append(item['target'])
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elif converter == 'avconv':
        cmd = ['avconv', '-i', item['origin']]
        if 'avconv' in profile:
            cmd.extend(profile['avconv'])
        cmd.append(item['target'])
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        msg = "Unknown converter: {conv}\n".format(conv=converter)
        sys.stderr.write(msg)
        raise UnknownConverter(msg)


def addtoconvert(newitem, items, args):
    # Avoid copy/converting twice to same destination
    # Not sure if debugging makes it harder or easier to read.
    debug(100, 'items:\n%s' % dformat(100, items))
    for item in items[newitem['origin']]:
        debug(1, "Comparing to name: {}, playlist: {}\n".format(item['origin'], item['playlist']))
        if item['origin'] == newitem['origin']:
            if item['playlist'] == newitem['playlist'] or not args.named:
                debug(1, "MATCHED.")
                # Break past for loop's else
                break
            else:
                debug(1, "No match (playlist).")
        else:
            debug("No match (name).")
    # This else is on the for loop. So we're only doing this if
    # we didn't match existing name & playlist (and therefore
    # take the break).
    else:
        items[newitem['origin']].append(newitem)
    return items


# Synology playlists seem to be UTF8 dir, Windows-1252 file
#
# But no! Not even windows-1252. Much is, but some already UTF8.
#
"""
This is based on Victor Stinner's pure-Python implementation of PEP 383: the "surrogateescape" error
handler of Python 3.
Source: misc/python/surrogateescape.py in https://bitbucket.org/haypo/misc
"""

# This code is released under the Python license and the BSD 2-clause license

import codecs
import sys

def maybe1252_handler(exc):
    mystring = exc.object[exc.start:exc.end]

    try:
        # we only decode
        if isinstance(exc, UnicodeDecodeError):
            # mystring is a byte-string in this case
            decoded = replace_1252_decode(mystring)
        else:
            raise exc
    except Not1252Error:
        raise exc
    return (decoded, exc.end)

class Not1252Error(Exception):
    pass

def replace_1252_decode(mybytes):
    """
    Returns a string
    """
    decoded = []
    for code in mybytes:
        if 0x80 <= code <= 0xFF:
            decoded.append(bytes([code]).decode('windows-1252'))
        elif code <= 0x7F:
            decoded.append(chr(code))
        else:
            # # It may be a bad byte
            # # Try swallowing it.
            # continue
            # print("RAISE!")
            raise NotASurrogateError
    return str().join(decoded)

codecs.register_error('maybe1252', maybe1252_handler)

def synofix(mfile):
    mbase = os.path.basename(mfile)
    mbase = mbase.decode('utf-8', errors='maybe1252')
    mdir = os.path.dirname(mfile).decode('utf-8')
    mfile = os.fsencode(os.path.join(mdir, mbase))
    return mfile

def m3u_readfile(path, items):
    # make path be bytes
    path = os.fsencode(path)
    plname = os.path.basename(path)
    if plname.endswith(b'.m3u'):
        plname = plname[:-4]
    m3ufile = open(path, 'rb')
    # Read and ignore 1st line (expect it to be '#EXTM3U')
    if m3ufile.readline() == '':
        return items
    for mfile in m3ufile.readlines():
        # strip trailing \n, \r
        mfile = re.sub(rb'[\n\r]*$', b'', mfile)
        mfile = unquote_to_bytes(mfile)
        if args.synofix:
            debug(1, "Synofix item: %s" % dformat(1, mfile))
            mfile = synofix(mfile)
            debug(1, "Synofixed item: %s" % dformat(1, mfile))
        if not mfile in items:
            debug(1, "Creating toconvert item: %s" % dformat(1, mfile))
            items[mfile] = []
        addtoconvert(
            {
                'copy': False,
                'uri': None,
                'origin': mfile,
                'playlist': plname,
            },
            items, args)


def m3u_getsources(args):
    # Read specified m3u playlists within dir at args.origin, add contents to OrderedDict and return
    toconvert = collections.OrderedDict()
    if os.path.isdir(args.origin):
        plfilenames = []
        for pl in args.pl_names:
            if pl.endswith('.m3u'):
                plfilenames.append(pl)
            else:
                plfilenames.append('%s.m3u' % pl)
        for m3ufile in os.listdir(args.origin):
            if m3ufile in plfilenames:
                m3u_readfile(os.path.join(args.origin, m3ufile), toconvert)
    else:
        m3u_readfile(args.origin, toconvert)
    return toconvert


def rb_getsources(args):
    pl_etree = xmlparse("{HOME}/.local/share/rhythmbox/playlists.xml".format_map(os.environ))
    root = pl_etree.getroot()
    playlists = root.findall(".//playlist[@type='static']")

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
                else:
                    debug(1, "Current name: {}, playlist: {}".format(name, unquote_to_bytes(plname)))
                addtoconvert(
                    {
                        'copy': False,
                        'uri': e.text,
                        'origin': name,
                        'playlist': unquote_to_bytes(plname),
                    },
                    toconvert, args)
    return toconvert


def translate(tfrom, tto, items):
    newitems = {}
    for key, itemlist in items.items():
        newlist = []
        newkey = key.replace(
            unquote_to_bytes(tfrom),
            unquote_to_bytes(tto),
            1)
        for item in itemlist:
            newitem = item.copy()
            neworigin = item['origin'].replace(
                unquote_to_bytes(tfrom),
                unquote_to_bytes(tto),
                1)
            debug(1, "Translating %s to %s!" % (item['origin'], neworigin))
            newitem['origin'] = neworigin
            newlist.append(newitem)
        newitems[newkey] = newlist
    return newitems


toconvert = m3u_getsources(args)

if args.translatefrom is not None:
    toconvert = translate(args.translatefrom, args.translateto, toconvert)

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
        debug(1, "dirname: " + dformat(1, dirname))
        debug(1, "oldfilename: " + dformat(1, oldfilename))
        debug(1, "mungename: " + dformat(1, mungename))
        item['dir'] = dirname
        # Switch or add appropriate extension
        filenameparts = oldfilename.rsplit(b'.', 1)
        sys.stderr.write("filenameparts is: " + pprint.pformat(filenameparts) + "\n")
        if len(filenameparts) == 2 and filenameparts[1].lower().decode('utf8') in extensions:
            item['extension'] = filenameparts[1].lower().decode('utf8')
            debug(1, "newfilename is 0th part of oldfilename plus profile extension")
            newfilename = b'.'.join((filenameparts[0], profile['ext'].encode()))
            # While we're at it, set bool to indicate if we can just copy
            # file rather than transcoding. Decision based on old extension.
            # Yuk.
            if filenameparts[1].lower() == profile['ext'] and not args.recode:
                item['copy'] = True
        else:
            item['extension'] = None
            debug(1, "newfilename is mungename plus profile extension")
            newfilename = b'.'.join((mungename, profile['ext'].encode()))
        # Put target back together again
        item['target'] = os.path.join(dirname, newfilename)

# Debug info
debug(1, dformat(1, toconvert))

# Convert/copy ALL THE THINGS.
errors = []
for itemlist in toconvert.values():
    for item in itemlist:
        if os.path.exists(item['target']):
            print("Skipping target (exists): {target}".format(target=item['target']))
            continue
        if not os.path.exists(item['origin']):
            print("Skipping origin (does not exist): {origin}".format(origin=item['origin']))
            continue
        if not os.path.isdir(item['dir']):
            print("Creating directory: {dirname}".format(dirname=item['dir']))
            subprocess.run(['mkdir', '-p', item['dir']], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if item['copy']:
            cmd = ['cp', item['origin'], item['target']]
            print("Copying: " + ' '.join(cmd))
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            print("Trying to convert from '%(origin)s' to '%(target)s'..." % item)
            for converter in preference:
                try:
                    if item['extension'] in handlers[converter]:
                        status = convert(item, converter, profile)
                        if status.returncode != 0:
                            errors.append({
                                'item': item,
                                'stdout': status.stdout,
                                'stderr': status.stderr,
                                'rc': status.returncode
                            })
                    break
                except FileNotFoundError as e:
                    print("Unable to use preferred converter '%s', File Not Found.\n" % converter)
                    errors.append({
                        'item': item,
                        'stdout': '',
                        'stderr': "Unable to use preferred converter '%s', File Not Found.\n" % converter,
                        'rc': None
                    })
            else:
                sys.stderr.write('No handler for extension: {ext}\n'.format(ext=item['extension']))
                errors.append({
                    'item': item,
                    'stdout': '',
                    'stderr': 'No handler for extension: {ext}\n'.format(ext=item['extension']),
                    'rc': None
                })

if errors:
    sys.stderr.write("ERRORS:\n")
for error in errors:
    sys.stderr.write("*****\nOrigin: %s\nStdout: %s\nStderr: %s\nRC: %s\n" %
                     (error['item']['origin'], error['stdout'], error['stderr'], error['rc'])
)
