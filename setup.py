#!/usr/bin/env python

# $HeadURL: http://svn.berlios.de/svnroot/repos/sonata/trunk/setup.py $
# $Id: setup.py 141 2006-09-11 04:51:07Z stonecrest $

import os

from distutils.core import setup, Extension

def capture(cmd):
    return os.popen(cmd).read().strip()

setup(name='Sonata',
        version='1.0.1',
        description='GTK+ client for the Music Player Daemon (MPD).',
        author='Scott Horowitz',
        author_email='stonecrest@gmail.com',
        url='http://sonata.berlios.de',
        classifiers=[
            'Development Status :: 4 - Beta',
            'Environment :: X11 Applications',
            'Intended Audience :: End Users/Desktop',
            'License :: GNU General Public License (GPL)',
            'Operating System :: Linux',
            'Programming Language :: Python',
            'Topic :: Multimedia :: Sound :: Players',
            ],
        py_modules = ['sonata', 'mpdclient3'],
        ext_modules=[Extension(
        "mmkeys", ["mmkeys/mmkeyspy.c", "mmkeys/mmkeys.c", "mmkeys/mmkeysmodule.c"],
        extra_compile_args=capture("pkg-config --cflags gtk+-2.0 pygtk-2.0").split(),
        extra_link_args=capture("pkg-config --libs gtk+-2.0 pygtk-2.0").split()
         ),],
        scripts = ['sonata'],
        data_files=[('share/sonata', ['README', 'CHANGELOG', 'TODO', 'TRANSLATORS']),
                    ('share/applications', ['sonata.desktop']),
                    ('share/pixmaps', ['pixmaps/sonata.png', 'pixmaps/sonata_large.png', 'pixmaps/sonatacd.png', 'pixmaps/sonatacd_large.png', 'pixmaps/sonata-artist.png', 'pixmaps/sonata-album.png', 'pixmaps/sonata-volume-mute.png', 'pixmaps/sonata-volume-min.png', 'pixmaps/sonata-volume-med.png', 'pixmaps/sonata-volume-max.png']),
                    ('share/locale/de/LC_MESSAGES', ['locale/de/LC_MESSAGES/sonata.mo']),
                    ('share/locale/pl/LC_MESSAGES', ['locale/pl/LC_MESSAGES/sonata.mo']),
                    ('share/locale/ru/LC_MESSAGES', ['locale/ru/LC_MESSAGES/sonata.mo']),
                    ('share/locale/fr/LC_MESSAGES', ['locale/fr/LC_MESSAGES/sonata.mo']),
                    ('share/locale/zh_CN/LC_MESSAGES', ['locale/zh_CN/LC_MESSAGES/sonata.mo']),
                    ('share/locale/uk/LC_MESSAGES', ['locale/uk/LC_MESSAGES/sonata.mo'])],
        )
