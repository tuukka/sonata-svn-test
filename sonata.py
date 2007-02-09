# coding=utf-8
# $HeadURL: http://svn.berlios.de/svnroot/repos/sonata/trunk/sonata.py $
# $Id: sonata.py 141 2006-09-11 04:51:07Z stonecrest $

__version__ = "1.0.1"

__license__ = """
Sonata, an elegant GTK+ client for the Music Player Daemon
Copyright 2006 Scott Horowitz <stonecrest@gmail.com>

This file is part of Sonata.

Sonata is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

Sonata is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Sonata; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
"""

import sys
import os
import gobject
import ConfigParser
import urllib, urllib2
import socket
import gc
import subprocess
import gettext
import locale
import shutil
import getopt
import threading

try:
	import mmkeys
	HAVE_MMKEYS = True
except:
	HAVE_MMKEYS = False

try:
	import gtk
	import pango
	import mpdclient3
except ImportError, (strerror):
	print >>sys.stderr, "%s.  Please make sure you have this library installed into a directory in Python's path or in the same directory as Sonata.\n" % strerror
	sys.exit(1)

try:
	import egg.trayicon
	HAVE_EGG = True
	HAVE_STATUS_ICON = False
except ImportError:
	HAVE_EGG = False
	if gtk.pygtk_version >= (2, 10, 0):
		# Revert to pygtk status icon:
		HAVE_STATUS_ICON = True
	else:
		HAVE_STATUS_ICON = False

try:
	import dbus
	import dbus.service
	if getattr(dbus, "version", (0,0,0)) >= (0,41,0):
		import dbus.glib
	HAVE_DBUS = True
except:
	HAVE_DBUS = False

try:
	import sugar
	HAVE_STATUS_ICON = False
	HAVE_SUGAR = True
	VOLUME_ICON_SIZE = 3
except:
	HAVE_SUGAR = False
	VOLUME_ICON_SIZE = 4

try:
	import tagpy
	HAVE_TAGPY = True
except:
	HAVE_TAGPY = False

try:
	# Temporarily disable lyrics...
	from SOAPpy import WSDL
	HAVE_WSDL = True
except:
	HAVE_WSDL = False

# Test pygtk version
if gtk.pygtk_version < (2, 6, 0):
	sys.stderr.write("Sonata requires PyGTK 2.6.0 or newer.\n")
	sys.exit(1)

class Connection(mpdclient3.mpd_connection):
	"""A connection to the daemon. Will use MPD_HOST/MPD_PORT in preference to the supplied config if available."""

	def __init__(self, Base):
		"""Open a connection using the host/port values from the provided config. If conf is None, an empty object will be returned, suitable for comparing != to any other connection."""
		host = Base.host
		port = Base.port
		password = Base.password

		if os.environ.has_key('MPD_HOST'):
			if '@' in os.environ['MPD_HOST']:
				password, host = os.environ['MPD_HOST'].split('@')
			else:
				host = os.environ['MPD_HOST']
		if os.environ.has_key('MPD_PORT'):
			port = int(os.environ['MPD_PORT'])

		mpdclient3.mpd_connection.__init__(self, host, port, password)
		mpdclient3.connect(host=host, port=port, password=password)

class Base(mpdclient3.mpd_connection):
	def __init__(self, window=None, sugar=False):

		gtk.gdk.threads_init()

		try:
			gettext.install('sonata', os.path.join(__file__.split('/lib')[0], 'share', 'locale'), unicode=1)
		except:
			gettext.install('sonata', '/usr/share/locale', unicode=1)

		self.traytips = TrayIconTips()

		toggle_arg = False
		# Read any passed options/arguments:
		if not sugar:
			try:
				opts, args = getopt.getopt(sys.argv[1:], "tv", ["toggle", "version", "status", "info", "play", "pause", "stop", "next", "prev", "pp"])
			except getopt.GetoptError:
				# print help information and exit:
				self.print_usage()
				sys.exit()
			# If options were passed, perform action on them.
			if opts != []:
				for o, a in opts:
					if o in ("-t", "--toggle"):
						toggle_arg = True
						if not HAVE_DBUS:
							print _("The toggle argument requires D-Bus. Aborting.")
							self.print_usage()
							sys.exit()
					elif o in ("-v", "--version"):
						self.print_version()
						sys.exit()
					else:
						self.print_usage()
						sys.exit()
			if args != []:
				for a in args:
					if a in ("play"):
						self.single_connect_for_passed_arg("play")
					elif a in ("pause"):
						self.single_connect_for_passed_arg("pause")
					elif a in ("stop"):
						self.single_connect_for_passed_arg("stop")
					elif a in ("next"):
						self.single_connect_for_passed_arg("next")
					elif a in ("prev"):
						self.single_connect_for_passed_arg("prev")
					elif a in ("pp"):
						self.single_connect_for_passed_arg("toggle")
					elif a in ("info"):
						self.single_connect_for_passed_arg("info")
					elif a in ("status"):
						self.single_connect_for_passed_arg("status")
					else:
 						self.print_usage()
 					sys.exit()
 		
 		if not HAVE_TAGPY:
			print "Taglib and tagpy not found, tag editing support disabled."
		if not HAVE_WSDL:
			print "SOAPpy not found, fetching lyrics support disabled."
		if not HAVE_EGG and not HAVE_STATUS_ICON:
			print "PyGTK+ 2.10 or gnome-python-extras not found, system tray support disabled."

		start_dbus_interface(toggle_arg)

		# Initialize vars:
		self.TAB_CURRENT = 0
		self.TAB_LIBRARY = 1
		self.TAB_PLAYLISTS = 2
		self.TAB_STREAMS = 3
		self.ART_LOCAL = 0
		self.ART_REMOTE = 1
		self.ART_LOCAL_REMOTE = 2
		self.ART_REMOTE_LOCAL = 3
		self.VIEW_FILESYSTEM = 0
		self.VIEW_ARTIST = 1
		self.VIEW_ALBUM = 2
		self.LYRIC_TIMEOUT = 10
		self.musicdir = os.path.expanduser("~/music")
		socket.setdefaulttimeout(2)
		self.host = 'localhost'
		self.port = 6600
		self.password = ''
		self.x = 0
		self.y = 0
		self.w = 400
		self.h = 300
		self.infowindow_x = 200
		self.infowindow_y = 200
		self.infowindow_w = 380
		self.infowindow_h = -1
		self.expanded = True
		self.visible = True
		self.withdrawn = False
		self.sticky = False
		self.ontop = False
		self.screen = 0
		self.prevconn = []
		self.prevstatus = None
		self.prevsonginfo = None
		self.lastalbumart = None
		self.xfade = 0
		self.xfade_enabled = False
		self.show_covers = True
		self.covers_pref = self.ART_LOCAL_REMOTE
		self.lyricServer = None
		self.show_volume = True
		self.show_notification = False
		self.show_playback = True
		self.show_statusbar = False
		self.show_trayicon = True
		self.show_lyrics = True
		self.stop_on_exit = False
		self.update_on_start = False
		self.minimize_to_systray = False
		self.popuptimes = ['2', '3', '5', '10', '15', '30', _('Entire song')]
		self.popuplocations = [_('System tray'), _('Top Left'), _('Top Right'), _('Bottom Left'), _('Bottom Right')]
		self.popup_option = 2
		self.exit_now = False
		self.ignore_toggle_signal = False
		self.initial_run = True
		self.currentformat = "%A - %S"
		self.libraryformat = "%A - %S"
		self.titleformat = "[Sonata] %A - %S"
		self.currsongformat1 = "%S"
		self.currsongformat2 = "by %A from %B"
		self.autoconnect = True
		self.user_connect = False
		self.stream_names = []
		self.stream_uris = []
		self.infowindow_visible = False
		self.downloading_image = False
		self.search_terms = [_('Artist'), _('Title'), _('Album'), _('Genre'), _('Filename')]
		self.search_terms_mpd = ['artist', 'title', 'album', 'genre', 'filename']
		self.sonata_loaded = False
		self.call_gc_collect = False
		self.single_img_in_dir = None
		self.total_time = 0
		self.prev_boldrow = -1
		self.use_infofile = False
		self.infofile_path = '/tmp/xmms-info'
		self.play_on_activate = False
		self.view = self.VIEW_FILESYSTEM
		self.view_artist_artist = ''
		self.view_artist_album = ''
		self.view_artist_level = 1
		self.view_artist_level_prev = 0
		self.remote_from_infowindow = False
		self.songs = None
		self.tagpy_is_91 = None
		show_prefs = False
		# For increased responsiveness after the initial load, we cache
		# the root artist and album view results and simply refresh on
		# any mpd update
		self.albums_root = None
		self.artists_root = None
		# If the connection to MPD times out, this will cause the
		# interface to freeze while the socket.connect() calls
		# are repeatedly executed. Therefore, if we were not
		# able to make a connection, slow down the iteration
		# check to once every 15 seconds.
		# Eventually we'd like to ues non-blocking sockets in
		# mpdclient3.py
		self.iterate_time_when_connected = 500
		self.iterate_time_when_disconnected = 15000

		self.settings_load()
		if self.autoconnect:
			self.user_connect = True

		# Add some icons:
		self.iconfactory = gtk.IconFactory()
		sonataset1 = gtk.IconSet()
		sonataset2 = gtk.IconSet()
		sonataset3 = gtk.IconSet()
		filename1 = [self.find_path('sonata.png')]
		filename2 = [self.find_path('sonata-artist.png')]
		filename3 = [self.find_path('sonata-album.png')]
		icons1 = [gtk.IconSource() for i in filename1]
		icons2 = [gtk.IconSource() for i in filename2]
		icons3 = [gtk.IconSource() for i in filename3]
		for i, iconsource in enumerate(icons1):
			iconsource.set_filename(filename1[i])
			sonataset1.add_source(iconsource)
		self.iconfactory.add('sonata', sonataset1)
		self.iconfactory.add_default()
		for i, iconsource in enumerate(icons2):
			iconsource.set_filename(filename2[i])
			sonataset2.add_source(iconsource)
		self.iconfactory.add('artist', sonataset2)
		self.iconfactory.add_default()
		for i, iconsource in enumerate(icons3):
			iconsource.set_filename(filename3[i])
			sonataset3.add_source(iconsource)
		self.iconfactory.add('album', sonataset3)
		self.iconfactory.add_default()

		# Popup menus:
		actions = (
			('sortmenu', None, _('_Sort List')),
			('filesystemview', gtk.STOCK_HARDDISK, _('Filesystem'), None, None, self.on_libraryview_chosen),
			('artistview', 'artist', _('Artist'), None, None, self.on_libraryview_chosen),
			('albumview', 'album', _('Album'), None, None, self.on_libraryview_chosen),
			('songinfo_menu', gtk.STOCK_INFO, _('Song Info...'), None, None, self.on_infowindow_show),
			('chooseimage_menu', gtk.STOCK_CONVERT, _('Use _Remote Image...'), None, None, self.on_choose_image),
			('localimage_menu', gtk.STOCK_OPEN, _('Use _Local Image...'), None, None, self.on_choose_image_local),
			('playmenu', gtk.STOCK_MEDIA_PLAY, _('_Play'), None, None, self.pp),
			('pausemenu', gtk.STOCK_MEDIA_PAUSE, _('_Pause'), None, None, self.pp),
			('stopmenu', gtk.STOCK_MEDIA_STOP, _('_Stop'), None, None, self.stop),
			('prevmenu', gtk.STOCK_MEDIA_PREVIOUS, _('_Previous'), None, None, self.prev),
			('nextmenu', gtk.STOCK_MEDIA_NEXT, _('_Next'), None, None, self.next),
			('quitmenu', gtk.STOCK_QUIT, _('_Quit'), None, None, self.on_delete_event_yes),
			('removemenu', gtk.STOCK_REMOVE, _('_Remove'), None, None, self.remove),
			('clearmenu', gtk.STOCK_CLEAR, _('_Clear'), '<Ctrl>Delete', None, self.clear),
			('savemenu', None, _('_Save Playlist...'), '<Ctrl><Shift>s', None, self.on_save_playlist),
			('updatemenu', None, _('_Update Library'), None, None, self.updatedb),
			('preferencemenu', gtk.STOCK_PREFERENCES, _('_Preferences...'), None, None, self.prefs),
			('aboutmenu', None, _('_About...'), 'F1', None, self.about),
			('newmenu', None, _('_New...'), '<Ctrl>n', None, self.streams_new),
			('editmenu', None, _('_Edit...'), None, None, self.streams_edit),
			('edittagmenu', None, _('_Edit Tags...'), None, None, self.edit_tags),
			('addmenu', gtk.STOCK_ADD, _('_Add'), '<Ctrl>d', None, self.add_item),
			('replacemenu', gtk.STOCK_REDO, _('_Replace'), '<Ctrl>r', None, self.replace_item),
			('rmmenu', None, _('_Delete...'), None, None, self.remove),
			('sortbyartist', None, _('By') + ' ' + _('Artist'), None, None, self.on_sort_by_artist),
			('sortbyalbum', None, _('By') + ' ' + _('Album'), None, None, self.on_sort_by_album),
			('sortbytitle', None, _('By') + ' ' + _('Song Title'), None, None, self.on_sort_by_title),
			('sortbyfile', None, _('By') + ' ' + _('File Name'), None, None, self.on_sort_by_file),
			('sortreverse', None, _('Reverse List'), None, None, self.on_sort_reverse),
			('sortrandom', None, _('Random'), None, None, self.on_sort_random),
			('currentkey', None, 'Current Playlist Key', '<Alt>1', None, self.switch_to_current),
			('librarykey', None, 'Library Key', '<Alt>2', None, self.switch_to_library),
			('playlistskey', None, 'Playlists Key', '<Alt>3', None, self.switch_to_playlists),
			('streamskey', None, 'Streams Key', '<Alt>4', None, self.switch_to_streams),
			('expandkey', None, 'Expand Key', '<Alt>Down', None, self.expand),
			('collapsekey', None, 'Collapse Key', '<Alt>Up', None, self.collapse),
			('ppkey', None, 'Play/Pause Key', '<Ctrl>p', None, self.pp),
			('stopkey', None, 'Stop Key', '<Ctrl>s', None, self.stop),
			('prevkey', None, 'Previous Key', '<Ctrl>Left', None, self.prev),
			('nextkey', None, 'Next Key', '<Ctrl>Right', None, self.next),
			('lowerkey', None, 'Lower Volume Key', '<Ctrl>minus', None, self.lower_volume),
			('raisekey', None, 'Raise Volume Key', '<Ctrl>plus', None, self.raise_volume),
			('raisekey2', None, 'Raise Volume Key 2', '<Ctrl>equal', None, self.raise_volume),
			('quitkey', None, 'Quit Key', '<Ctrl>q', None, self.on_delete_event_yes),
			('quitkey2', None, 'Quit Key 2', '<Ctrl>w', None, self.on_delete_event_yes),
			('menukey', None, 'Menu Key', 'Menu', None, self.menukey_press),
			('updatekey', None, 'Update Key', '<Ctrl>u', None, self.updatedb),
			('updatekey2', None, 'Update Key 2', '<Ctrl><Shift>u', None, self.updatedb_path),
			('connectkey', None, 'Connect Key', '<Alt>c', None, self.connectkey_pressed),
			('disconnectkey', None, 'Disconnect Key', '<Alt>d', None, self.disconnectkey_pressed),
			)

		toggle_actions = (
			('showmenu', None, _('_Show Player'), None, None, self.withdraw_app_toggle, not self.withdrawn),
			('repeatmenu', None, _('_Repeat'), None, None, self.on_repeat_clicked, False),
			('shufflemenu', None, _('_Shuffle'), None, None, self.on_shuffle_clicked, False),
				)

		uiDescription = """
			<ui>
			  <popup name="imagemenu">
			    <menuitem action="chooseimage_menu"/>
			    <menuitem action="localimage_menu"/>
			  </popup>
			  <popup name="traymenu">
			    <menuitem action="showmenu"/>
			    <separator name="FM1"/>
			    <menuitem action="playmenu"/>
			    <menuitem action="pausemenu"/>
			    <menuitem action="stopmenu"/>
			    <menuitem action="prevmenu"/>
			    <menuitem action="nextmenu"/>
			    <separator name="FM2"/>
			    <menuitem action="quitmenu"/>
			  </popup>
			  <popup name="mainmenu">
			    <menuitem action="addmenu"/>
			    <menuitem action="replacemenu"/>
			    <menuitem action="newmenu"/>
			    <menuitem action="editmenu"/>
			    <menuitem action="removemenu"/>
			    <menuitem action="clearmenu"/>
			    <menuitem action="savemenu"/>
			    <menuitem action="edittagmenu"/>
			    <menuitem action="rmmenu"/>
			    <menuitem action="updatemenu"/>
			    <menu action="sortmenu">
			      <menuitem action="sortbytitle"/>
			      <menuitem action="sortbyartist"/>
			      <menuitem action="sortbyalbum"/>
			      <menuitem action="sortbyfile"/>
			      <separator name="FM3"/>
			      <menuitem action="sortrandom"/>
			      <menuitem action="sortreverse"/>
			    </menu>
			    <menuitem action="songinfo_menu"/>
			    <separator name="FM1"/>
			    <menuitem action="repeatmenu"/>
			    <menuitem action="shufflemenu"/>
			    <separator name="FM2"/>
			    <menuitem action="preferencemenu"/>
			    <menuitem action="aboutmenu"/>
			    <menuitem action="quitmenu"/>
			  </popup>
			  <popup name="librarymenu">
			    <menuitem action="filesystemview"/>
			    <menuitem action="artistview"/>
			    <menuitem action="albumview"/>
			  </popup>
			  <popup name="hidden">
				<menuitem action="quitkey"/>
				<menuitem action="quitkey2"/>
				<menuitem action="currentkey"/>
				<menuitem action="librarykey"/>
				<menuitem action="playlistskey"/>
				<menuitem action="streamskey"/>
				<menuitem action="expandkey"/>
				<menuitem action="collapsekey"/>
				<menuitem action="ppkey"/>
				<menuitem action="stopkey"/>
				<menuitem action="nextkey"/>
				<menuitem action="prevkey"/>
				<menuitem action="lowerkey"/>
				<menuitem action="raisekey"/>
				<menuitem action="raisekey2"/>
				<menuitem action="menukey"/>
				<menuitem action="updatekey"/>
				<menuitem action="updatekey2"/>
				<menuitem action="connectkey"/>
				<menuitem action="disconnectkey"/>
			  </popup>
			</ui>
			"""

		# Try to connect to MPD:
		self.conn = self.connect()
		if self.conn:
			self.conn.do.password(self.password)
			self.status = self.conn.do.status()
			self.iterate_time = self.iterate_time_when_connected
			try:
				test = self.status.state
			except:
				self.status = None
			try:
				self.songinfo = self.conn.do.currentsong()
			except:
				self.songinfo = None
		else:
			if self.initial_run:
				show_prefs = True
			self.iterate_time = self.iterate_time_when_disconnected
			self.status = None
			self.songinfo = None

		# Remove the old sonata covers dir (cleanup)
		if os.path.exists(os.path.expanduser('~/.config/sonata/covers/')):
			removeall(os.path.expanduser('~/.config/sonata/covers/'))
			os.rmdir(os.path.expanduser('~/.config/sonata/covers/'))

		# Main app:
		if window is None:
			self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
			self.window_owner = True
		else:
			self.window = window
			self.window_owner = False

 		if self.window_owner:
			self.window.set_title('Sonata')
			self.window.set_resizable(True)
			if self.ontop:
				self.window.set_keep_above(True)
			if self.sticky:
				self.window.stick()
		if HAVE_SUGAR:
			theme = gtk.icon_theme_get_default()
			theme.append_search_path(os.path.join(os.path.split(__file__)[0], 'share'))
		self.tooltips = gtk.Tooltips()
		self.UIManager = gtk.UIManager()
		actionGroup = gtk.ActionGroup('Actions')
		actionGroup.add_actions(actions)
		actionGroup.add_toggle_actions(toggle_actions)
		self.UIManager.insert_action_group(actionGroup, 0)
		self.UIManager.add_ui_from_string(uiDescription)
		self.window.add_accel_group(self.UIManager.get_accel_group())
		self.mainmenu = self.UIManager.get_widget('/mainmenu')
		self.shufflemenu = self.UIManager.get_widget('/mainmenu/shufflemenu')
		self.repeatmenu = self.UIManager.get_widget('/mainmenu/repeatmenu')
		self.imagemenu = self.UIManager.get_widget('/imagemenu')
		self.traymenu = self.UIManager.get_widget('/traymenu')
		self.librarymenu = self.UIManager.get_widget('/librarymenu')
		mainhbox = gtk.HBox()
		mainvbox = gtk.VBox()
		tophbox = gtk.HBox()
		self.imageeventbox = gtk.EventBox()
		self.imageeventbox.drag_dest_set(gtk.DEST_DEFAULT_HIGHLIGHT | gtk.DEST_DEFAULT_DROP, [("text/uri-list", 0, 80)], gtk.gdk.ACTION_DEFAULT)
		self.albumimage = gtk.Image()
		self.imageeventbox.add(self.albumimage)
		if not self.show_covers:
			self.imageeventbox.set_no_show_all(True)
			self.imageeventbox.hide()
		tophbox.pack_start(self.imageeventbox, False, False, 5)
		topvbox = gtk.VBox()
		toptophbox = gtk.HBox()
		self.prevbutton = gtk.Button("", gtk.STOCK_MEDIA_PREVIOUS, True)
		self.prevbutton.set_relief(gtk.RELIEF_NONE)
		self.prevbutton.set_property('can-focus', False)
		self.prevbutton.get_child().get_child().get_children()[1].set_text('')
		toptophbox.pack_start(self.prevbutton, False, False, 0)
		self.ppbutton = gtk.Button("", gtk.STOCK_MEDIA_PLAY, True)
		self.ppbutton.set_relief(gtk.RELIEF_NONE)
		self.ppbutton.set_property('can-focus', False)
		self.ppbutton.get_child().get_child().get_children()[1].set_text('')
		toptophbox.pack_start(self.ppbutton, False, False, 0)
		self.stopbutton = gtk.Button("", gtk.STOCK_MEDIA_STOP, True)
		self.stopbutton.set_relief(gtk.RELIEF_NONE)
		self.stopbutton.set_property('can-focus', False)
		self.stopbutton.get_child().get_child().get_children()[1].set_text('')
		toptophbox.pack_start(self.stopbutton, False, False, 0)
		self.nextbutton = gtk.Button("", gtk.STOCK_MEDIA_NEXT, True)
		self.nextbutton.set_relief(gtk.RELIEF_NONE)
		self.nextbutton.set_property('can-focus', False)
		self.nextbutton.get_child().get_child().get_children()[1].set_text('')
		toptophbox.pack_start(self.nextbutton, False, False, 0)
		if not self.show_playback:
			self.prevbutton.set_no_show_all(True)
			self.ppbutton.set_no_show_all(True)
			self.stopbutton.set_no_show_all(True)
			self.nextbutton.set_no_show_all(True)
			self.prevbutton.hide()
			self.ppbutton.hide()
			self.stopbutton.hide()
			self.nextbutton.hide()
		progressbox = gtk.VBox()
		self.progresslabel = gtk.Label()
		self.progresslabel.set_size_request(-1, 6)
		progressbox.pack_start(self.progresslabel)
		self.progresseventbox = gtk.EventBox()
		self.progressbar = gtk.ProgressBar()
		self.progressbar.set_orientation(gtk.PROGRESS_LEFT_TO_RIGHT)
		self.progressbar.set_fraction(0)
		self.progressbar.set_pulse_step(0.05)
		self.progressbar.set_ellipsize(pango.ELLIPSIZE_END)
		self.progresseventbox.add(self.progressbar)
		progressbox.pack_start(self.progresseventbox, False, False, 0)
		self.progresslabel2 = gtk.Label()
		self.progresslabel2.set_size_request(-1, 6)
		progressbox.pack_start(self.progresslabel2)
		toptophbox.pack_start(progressbox, True, True, 0)
		self.volumebutton = gtk.ToggleButton("", True)
		self.volumebutton.set_relief(gtk.RELIEF_NONE)
		self.volumebutton.set_property('can-focus', False)
		self.volumebutton.set_image(gtk.image_new_from_icon_name("stock_volume-med", VOLUME_ICON_SIZE))
		if not self.show_volume:
			self.volumebutton.set_no_show_all(True)
			self.volumebutton.hide()
		toptophbox.pack_start(self.volumebutton, False, False, 0)
		topvbox.pack_start(toptophbox, False, False, 2)
		self.expander = gtk.Expander(_("Playlist"))
		self.expander.set_expanded(self.expanded)
		self.expander.set_property('can-focus', False)
		self.cursonglabel = gtk.Label()
		self.expander.set_label_widget(self.cursonglabel)
		topvbox.pack_start(self.expander, False, False, 2)
		tophbox.pack_start(topvbox, True, True, 3)
		mainvbox.pack_start(tophbox, False, False, 5)
		self.notebook = gtk.Notebook()
		self.notebook.set_tab_pos(gtk.POS_TOP)
		self.notebook.set_property('can-focus', False)
		self.expanderwindow = gtk.ScrolledWindow()
		self.expanderwindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		self.expanderwindow.set_shadow_type(gtk.SHADOW_IN)
		self.current = gtk.TreeView()
		self.current.set_headers_visible(False)
		self.current.set_rules_hint(True)
		self.current.set_reorderable(True)
		self.current.set_enable_search(True)
		self.current_selection = self.current.get_selection()
		self.expanderwindow.add(self.current)
		playlisthbox = gtk.HBox()
		playlisthbox.pack_start(gtk.image_new_from_stock(gtk.STOCK_CDROM, gtk.ICON_SIZE_MENU), False, False, 2)
		playlisthbox.pack_start(gtk.Label(str=_("Current")), False, False, 2)
		playlisthbox.show_all()
		self.notebook.append_page(self.expanderwindow, playlisthbox)
		browservbox = gtk.VBox()
		self.expanderwindow2 = gtk.ScrolledWindow()
		self.expanderwindow2.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		self.expanderwindow2.set_shadow_type(gtk.SHADOW_IN)
		self.browser = gtk.TreeView()
		self.browser.set_headers_visible(False)
		self.browser.set_rules_hint(True)
		self.browser.set_reorderable(False)
		self.browser.set_enable_search(True)
		self.browser_selection = self.browser.get_selection()
		self.expanderwindow2.add(self.browser)
		self.searchbox = gtk.HBox()
		self.searchcombo = gtk.combo_box_new_text()
		for item in self.search_terms:
			self.searchcombo.append_text(item)
		self.searchtext = gtk.Entry()
		self.searchbutton = gtk.Button(_('_End Search'))
		self.searchbutton.set_image(gtk.image_new_from_stock(gtk.STOCK_CANCEL, gtk.ICON_SIZE_SMALL_TOOLBAR))
		self.searchbutton.set_size_request(-1, self.searchcombo.size_request()[1])
		self.searchbutton.set_no_show_all(True)
		self.searchbutton.hide()
		self.libraryview = gtk.Button()
		self.tooltips.set_tip(self.libraryview, _("Library browsing view"))
		self.libraryview_assign_image()
		self.libraryview.set_relief(gtk.RELIEF_NONE)
		self.librarymenu.attach_to_widget(self.libraryview, None)
		self.searchbox.pack_start(self.libraryview, False, False, 1)
		self.searchbox.pack_start(gtk.VSeparator(), False, False, 0)
		self.searchbox.pack_start(self.searchcombo, False, False, 2)
		self.searchbox.pack_start(self.searchtext, True, True, 2)
		self.searchbox.pack_start(self.searchbutton, False, False, 2)
		browservbox.pack_start(self.expanderwindow2, True, True, 2)
		browservbox.pack_start(self.searchbox, False, False, 2)
		libraryhbox = gtk.HBox()
		libraryhbox.pack_start(gtk.image_new_from_stock(gtk.STOCK_HARDDISK, gtk.ICON_SIZE_MENU), False, False, 2)
		libraryhbox.pack_start(gtk.Label(str=_("Library")), False, False, 2)
		libraryhbox.show_all()
		self.notebook.append_page(browservbox, libraryhbox)
		self.expanderwindow3 = gtk.ScrolledWindow()
		self.expanderwindow3.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		self.expanderwindow3.set_shadow_type(gtk.SHADOW_IN)
		self.playlists = gtk.TreeView()
		self.playlists.set_headers_visible(False)
		self.playlists.set_rules_hint(True)
		self.playlists.set_reorderable(False)
		self.playlists.set_enable_search(True)
		self.playlists_selection = self.playlists.get_selection()
		self.expanderwindow3.add(self.playlists)
		playlistshbox = gtk.HBox()
		playlistshbox.pack_start(gtk.image_new_from_stock(gtk.STOCK_JUSTIFY_FILL, gtk.ICON_SIZE_MENU), False, False, 2)
		playlistshbox.pack_start(gtk.Label(str=_("Playlists")), False, False, 2)
		playlistshbox.show_all()
		self.notebook.append_page(self.expanderwindow3, playlistshbox)
		self.expanderwindow4 = gtk.ScrolledWindow()
		self.expanderwindow4.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		self.expanderwindow4.set_shadow_type(gtk.SHADOW_IN)
		self.streams = gtk.TreeView()
		self.streams.set_headers_visible(False)
		self.streams.set_rules_hint(True)
		self.streams.set_reorderable(False)
		self.streams.set_enable_search(True)
		self.streams_selection = self.streams.get_selection()
		self.expanderwindow4.add(self.streams)
		streamshbox = gtk.HBox()
		streamshbox.pack_start(gtk.image_new_from_stock(gtk.STOCK_NETWORK, gtk.ICON_SIZE_MENU), False, False, 2)
		streamshbox.pack_start(gtk.Label(str=_("Streams")), False, False, 2)
		streamshbox.show_all()
		self.notebook.append_page(self.expanderwindow4, streamshbox)
		mainvbox.pack_start(self.notebook, True, True, 5)
		self.statusbar = gtk.Statusbar()
		self.statusbar.set_has_resize_grip(True)
		if not self.show_statusbar or not self.expanded:
			self.statusbar.hide()
			self.statusbar.set_no_show_all(True)
		mainvbox.pack_start(self.statusbar, False, False, 0)
		mainhbox.pack_start(mainvbox, True, True, 3)
		self.window.add(mainhbox)
		if self.window_owner:
			self.window.move(self.x, self.y)
			self.window.set_size_request(270, -1)
		if not self.expanded:
			self.notebook.set_no_show_all(True)
			self.notebook.hide()
			self.cursonglabel.set_markup('<big><b>' + _('Stopped') + '</b></big>\n<small>' + _('Click to expand') + '</small>')
			if self.window_owner:
				self.window.set_default_size(self.w, 1)
		else:
			self.cursonglabel.set_markup('<big><b>' + _('Stopped') + '</b></big>\n<small>' + _('Click to collapse') + '</small>')
			if self.window_owner:
				self.window.set_default_size(self.w, self.h)
		if not self.conn:
			self.progressbar.set_text(_('Not Connected'))
		if self.expanded:
			self.tooltips.set_tip(self.expander, _("Click to collapse the player"))
		else:
			self.tooltips.set_tip(self.expander, _("Click to expand the player"))

		# Systray:
		outtertipbox = gtk.VBox()
		tipbox = gtk.HBox()
		self.trayalbumeventbox = gtk.EventBox()
		self.trayalbumeventbox.set_size_request(59, 90)
		self.trayalbumimage1 = gtk.Image()
		self.trayalbumimage1.set_size_request(51, 77)
		self.trayalbumimage1.set_alignment(1, 0.5)
		self.trayalbumeventbox.add(self.trayalbumimage1)
		self.trayalbumeventbox.set_state(gtk.STATE_SELECTED)
		hiddenlbl = gtk.Label()
		hiddenlbl.set_size_request(2, -1)
		tipbox.pack_start(hiddenlbl, False, False, 0)
		tipbox.pack_start(self.trayalbumeventbox, False, False, 0)
		self.trayalbumimage2 = gtk.Image()
		self.trayalbumimage2.set_size_request(26, 77)
		tipbox.pack_start(self.trayalbumimage2, False, False, 0)
		if not self.show_covers:
			self.trayalbumeventbox.set_no_show_all(True)
			self.trayalbumeventbox.hide()
			self.trayalbumimage2.set_no_show_all(True)
			self.trayalbumimage2.hide()
		innerbox = gtk.VBox()
		self.traycursonglabel = gtk.Label()
		self.traycursonglabel.set_markup(_("Playlist"))
		self.traycursonglabel.set_alignment(0, 1)
		label1 = gtk.Label()
		label1.set_markup('<span size="10"> </span>')
		innerbox.pack_start(label1)
		innerbox.pack_start(self.traycursonglabel, True, True, 0)
		self.trayprogressbar = gtk.ProgressBar()
		self.trayprogressbar.set_orientation(gtk.PROGRESS_LEFT_TO_RIGHT)
		self.trayprogressbar.set_fraction(0)
		self.trayprogressbar.set_pulse_step(0.05)
		self.trayprogressbar.set_ellipsize(pango.ELLIPSIZE_NONE)
		label2 = gtk.Label()
		label2.set_markup('<span size="10"> </span>')
		innerbox.pack_start(label2)
		innerbox.pack_start(self.trayprogressbar, False, False, 0)
		label3 = gtk.Label()
		label3.set_markup('<span size="10"> </span>')
		innerbox.pack_start(label3)
		tipbox.pack_start(innerbox, True, True, 6)
		outtertipbox.pack_start(tipbox, False, False, 2)
		outtertipbox.show_all()
		self.traytips.add_widget(outtertipbox)

		# Volumescale window
		self.volumewindow = gtk.Window(gtk.WINDOW_POPUP)
		self.volumewindow.set_skip_taskbar_hint(True)
		self.volumewindow.set_skip_pager_hint(True)
		self.volumewindow.set_decorated(False)
		frame = gtk.Frame()
		frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
		self.volumewindow.add(frame)
		volbox = gtk.VBox()
		volbox.pack_start(gtk.Label("+"), False, False, 0)
		self.volumescale = gtk.VScale()
		self.volumescale.set_draw_value(True)
		self.volumescale.set_value_pos(gtk.POS_TOP)
		self.volumescale.set_digits(0)
		self.volumescale.set_update_policy(gtk.UPDATE_CONTINUOUS)
		self.volumescale.set_inverted(True)
		self.volumescale.set_adjustment(gtk.Adjustment(0, 0, 100, 0, 0, 0))
		if HAVE_SUGAR:
			self.volumescale.set_size_request(-1, 203)
		else:
			self.volumescale.set_size_request(-1, 103)
		volbox.pack_start(self.volumescale, True, True, 0)
		volbox.pack_start(gtk.Label("-"), False, False, 0)
		frame.add(volbox)
		frame.show_all()

		# Connect to signals
		self.window.add_events(gtk.gdk.BUTTON_PRESS_MASK)
		self.traytips.add_events(gtk.gdk.BUTTON_PRESS_MASK)
		self.traytips.connect('button_press_event', self.on_traytips_press)
		self.window.connect('delete_event', self.on_delete_event)
		self.window.connect('window_state_event', self.on_window_state_change)
		self.window.connect('configure_event', self.on_window_configure)
		self.window.connect('key-press-event', self.on_topwindow_keypress)
		self.window.connect('focus-out-event', self.on_window_lost_focus)
		self.imageeventbox.connect('button_press_event', self.on_image_activate)
		self.imageeventbox.connect('drag_motion', self.on_image_motion_cb)
		self.imageeventbox.connect('drag_data_received', self.on_image_drop_cb)
		self.ppbutton.connect('clicked', self.pp)
		self.stopbutton.connect('clicked', self.stop)
		self.prevbutton.connect('clicked', self.prev)
		self.nextbutton.connect('clicked', self.next)
		self.progresseventbox.connect('button_press_event', self.on_progressbar_button_press_event)
		self.progresseventbox.connect('scroll_event', self.on_progressbar_scroll_event)
		self.volumebutton.connect('clicked', self.on_volumebutton_clicked)
		self.volumebutton.connect('scroll-event', self.on_volumebutton_scroll)
		self.expander.connect('activate', self.on_expander_activate)
		self.current.connect('drag_data_received', self.on_drag_drop)
		self.current.connect('row_activated', self.on_current_click)
		self.current.connect('button_press_event', self.on_current_button_press)
		self.current.connect('button_release_event', self.on_current_button_released)
		self.current_selection.connect('changed', self.on_treeview_selection_changed)
		self.current.connect('popup_menu', self.on_current_popup_menu)
		self.shufflemenu.connect('toggled', self.on_shuffle_clicked)
		self.repeatmenu.connect('toggled', self.on_repeat_clicked)
		self.volumescale.connect('change_value', self.on_volumescale_change)
		self.volumescale.connect('scroll-event', self.on_volumescale_scroll)
		self.cursonglabel.connect('notify::label', self.labelnotify)
		self.progressbar.connect('notify::fraction', self.progressbarnotify_fraction)
		self.progressbar.connect('notify::text', self.progressbarnotify_text)
		self.browser.connect('row_activated', self.on_browse_row)
		self.browser.connect('button_press_event', self.on_browser_button_press)
		self.browser.connect('key-press-event', self.on_browser_key_press)
		self.browser_selection.connect('changed', self.on_treeview_selection_changed)
		self.libraryview.connect('clicked', self.libraryview_popup)
		self.playlists.connect('button_press_event', self.playlists_button_press)
		self.playlists.connect('row_activated', self.playlists_activated)
		self.playlists_selection.connect('changed', self.on_treeview_selection_changed)
		self.playlists.connect('key-press-event', self.playlists_key_press)
		self.streams.connect('button_press_event', self.streams_button_press)
		self.streams.connect('row_activated', self.on_streams_activated)
		self.streams_selection.connect('changed', self.on_treeview_selection_changed)
		self.streams.connect('key-press-event', self.on_streams_key_press)
		self.ppbutton.connect('button_press_event', self.popup_menu)
		self.prevbutton.connect('button_press_event', self.popup_menu)
		self.stopbutton.connect('button_press_event', self.popup_menu)
		self.nextbutton.connect('button_press_event', self.popup_menu)
		self.progresseventbox.connect('button_press_event', self.popup_menu)
		self.expander.connect('button_press_event', self.popup_menu)
		self.volumebutton.connect('button_press_event', self.popup_menu)
		self.mainwinhandler = self.window.connect('button_press_event', self.on_window_click)
		self.searchtext.connect('activate', self.on_search_activate)
		self.searchbutton.connect('clicked', self.on_search_end)
		self.notebook.connect('button_press_event', self.on_notebook_click)
		self.notebook.connect('switch-page', self.on_notebook_page_change)
		self.searchtext.connect('button_press_event', self.on_searchtext_click)
		self.initialize_systrayicon()

		# Connect to mmkeys signals
		if HAVE_MMKEYS:
			self.keys = mmkeys.MmKeys()
			self.keys.connect("mm_prev", self.mmprev)
			self.keys.connect("mm_next", self.mmnext)
			self.keys.connect("mm_playpause", self.mmpp)
			self.keys.connect("mm_stop", self.mmstop)

		# Put blank cd to albumimage widget by default
		self.sonatacd = self.find_path('sonatacd.png')
		self.sonatacd_large = self.find_path('sonatacd_large.png')
		self.albumimage.set_from_file(self.sonatacd)

		# Initialize current playlist data and widget
		self.currentdata = gtk.ListStore(int, str)
		self.current.set_model(self.currentdata)
		self.current.set_search_column(1)
		self.currentcell = gtk.CellRendererText()
		self.currentcolumn = gtk.TreeViewColumn('Pango Markup', self.currentcell, markup=1)
		self.currentcolumn.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
		self.current.append_column(self.currentcolumn)
		self.current_selection.set_mode(gtk.SELECTION_MULTIPLE)
		self.current.enable_model_drag_source(gtk.gdk.BUTTON1_MASK, [('STRING', 0, 0)], gtk.gdk.ACTION_MOVE)
		self.current.enable_model_drag_dest([('STRING', 0, 0)], gtk.gdk.ACTION_MOVE)
		self.current.set_fixed_height_mode(True)

		# Initialize playlist data and widget
		self.playlistsdata = gtk.ListStore(str, str)
		self.playlists.set_model(self.playlistsdata)
		self.playlists.set_search_column(1)
		self.playlistsimg = gtk.CellRendererPixbuf()
		self.playlistscell = gtk.CellRendererText()
		self.playlistscolumn = gtk.TreeViewColumn()
		self.playlistscolumn.pack_start(self.playlistsimg, False)
		self.playlistscolumn.pack_start(self.playlistscell, True)
		self.playlistscolumn.set_attributes(self.playlistsimg, stock_id=0)
		self.playlistscolumn.set_attributes(self.playlistscell, markup=1)
		self.playlists.append_column(self.playlistscolumn)
		self.playlists_selection.set_mode(gtk.SELECTION_MULTIPLE)

		# Initialize streams data and widget
		self.streamsdata = gtk.ListStore(str, str, str)
		self.streams.set_model(self.streamsdata)
		self.streams.set_search_column(1)
		self.streamsimg = gtk.CellRendererPixbuf()
		self.streamscell = gtk.CellRendererText()
		self.streamscolumn = gtk.TreeViewColumn()
		self.streamscolumn.pack_start(self.streamsimg, False)
		self.streamscolumn.pack_start(self.streamscell, True)
		self.streamscolumn.set_attributes(self.streamsimg, stock_id=0)
		self.streamscolumn.set_attributes(self.streamscell, markup=1)
		self.streams.append_column(self.streamscolumn)
		self.streams_selection.set_mode(gtk.SELECTION_MULTIPLE)

		# Initialize browser data and widget
		self.browserposition = {}
		self.browserselectedpath = {}
		self.root = '/'
		self.browser.wd = '/'
		self.searchcombo.set_active(0)
		self.prevstatus = None
		self.browserdata = gtk.ListStore(str, str, str)
		self.browser.set_model(self.browserdata)
		self.browser.set_search_column(2)
		self.browsercell = gtk.CellRendererText()
		self.browserimg = gtk.CellRendererPixbuf()
		self.browsercolumn = gtk.TreeViewColumn()
		self.browsercolumn.pack_start(self.browserimg, False)
		self.browsercolumn.pack_start(self.browsercell, True)
		self.browsercolumn.set_attributes(self.browserimg, stock_id=0)
		self.browsercolumn.set_attributes(self.browsercell, markup=2)
		self.browsercolumn.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
		self.browser.append_column(self.browsercolumn)
		self.browser_selection.set_mode(gtk.SELECTION_MULTIPLE)
		self.browser.set_fixed_height_mode(True)

		if self.window_owner:
			icon = self.window.render_icon('sonata', gtk.ICON_SIZE_DIALOG)
			self.window.set_icon(icon)

		self.streams_populate()

		self.iterate_now()
		if self.window_owner:
			if self.withdrawn and (HAVE_EGG or (HAVE_STATUS_ICON and self.statusicon.get_visible())):
				self.window.set_no_show_all(True)
				self.window.hide()
		self.window.show_all()

		if self.update_on_start:
			self.updatedb(None)

		self.notebook.set_no_show_all(False)
		self.window.set_no_show_all(False)

		if show_prefs:
			self.prefs(None)

		self.initial_run = False

		# Ensure that sonata is loaded before we display the notif window
		self.sonata_loaded = True
		self.labelnotify()
		self.keep_song_visible_in_list()
		
		if HAVE_STATUS_ICON:
			gobject.timeout_add(250, self.iterate_status_icon)

	def print_version(self):
		print _("Version: Sonata"), __version__
		print _("Website: http://sonata.berlios.de")

	def print_usage(self):
		self.print_version()
		print ""
		print _("Usage: sonata [OPTION]")
		print ""
		print _("Options") + ":"
		print "  -h, --help           " + _("Show this help and exit")
		print "  -v, --version        " + _("Show version information and exit")
		print "  -t, --toggle         " + _("Toggles whether the app is minimized")
		print "                       " + _("to tray or visible (requires D-Bus)")
		print "  play                 " + _("Play song in playlist")
		print "  pause                " + _("Pause currently playing song")
		print "  stop                 " + _("Stop currently playing song")
		print "  next                 " + _("Play next song in playlist")
		print "  prev                 " + _("Play previous song in playlist")
		print "  pp                   " + _("Toggle play/pause; plays if stopped")
		print "  info                 " + _("Display current song info")
		print "  status               " + _("Display MPD status")

	def single_connect_for_passed_arg(self, type):
		self.user_connect = True
		self.settings_load()
		self.conn = None
		self.conn = self.connect()
		if self.conn:
			self.conn.do.password(self.password)
			self.status = self.conn.do.status()
			try:
				test = self.status.state
			except:
				self.status = None
			try:
				self.songinfo = self.conn.do.currentsong()
			except:
				self.songinfo = None
			if type == "play":
				self.conn.do.play()
			elif type == "pause": 
				self.conn.do.pause(1)
			elif type == "stop":
				self.conn.do.stop()
			elif type == "next":
				self.conn.do.next()
			elif type == "prev":
				self.conn.do.previous()
			elif type == "toggle":
				self.status = self.conn.do.status()
				if self.status:
					if self.status.state in ['play']:
						self.conn.do.pause(1)
					elif self.status.state in ['pause', 'stop']:
						self.conn.do.play()
			elif type == "info":
				if self.status and self.status.state in ['play', 'pause']:
					print _("Title") + ": " + getattr(self.songinfo, 'title', '')
					print _("Artist") + ": " + getattr(self.songinfo, 'artist', '')
					print _("Album") + ": " + getattr(self.songinfo, 'album', '')
					print _("Date") + ": " + getattr(self.songinfo, 'date', '')
					try:
						print _("Track") + ": " + str(int(self.songinfo.track.split('/')[0]))
					except:
						pass
					print _("Genre") + ": " + getattr(self.songinfo, 'genre', '')
					print _("File") + ": " + os.path.basename(self.songinfo.file)
					at, length = [int(c) for c in self.status.time.split(':')]
					at_time = convert_time(at)
					try:
						time = convert_time(int(self.songinfo.time))
						print _("Time") + ": " + at_time + " / " + time
					except:
						print _("Time") + ": " + at_time
					print _("Bitrate") + ": " + getattr(self.status, 'bitrate', '')
				else:
					print _("MPD stopped")
			elif type == "status":
				if self.status:
					try:
						if self.status.state == 'play':
							print _("State") + ": " + _("Playing")
						elif self.status.state == 'pause':
							print _("State") + ": " + _("Paused")
						elif self.status.state == 'stop':
							print _("State") + ": " + _("Stopped")
						if self.status.repeat == '0':
							print _("Repeat") + ": " + _("Off")
						else:
							print _("Repeat") + ": " + _("On")
						if self.status.random == '0':
							print _("Shuffle") + ": " + _("Off")
						else:
							print _("Shuffle") + ": " + _("On")
						print _("Volume") + ": " + self.status.volume + "/100"
						if self.status.xfade == '1':
							print _('Crossfade') + ": " + self.status.xfade + ' ' + _('second')
						else:
							print _('Crossfade') + ": " + self.status.xfade + ' ' + _('seconds')
					except:
						pass
		else:
			print _("Unable to connect to MPD.\nPlease check your Sonata preferences.")

	def connect(self):
		if self.user_connect:
			try:
				return Connection(self)
			except (mpdclient3.socket.error, EOFError):
				return None
		else:
			return None

	def connectbutton_clicked(self, connectbutton, disconnectbutton, hostentry, portentry, passwordentry):
		connectbutton.set_sensitive(False)
		disconnectbutton.set_sensitive(True)
		if hostentry.get_text() != self.host or portentry.get_text() != str(self.port) or passwordentry.get_text() != self.password:
			self.host = hostentry.get_text()
			try:
				self.port = int(portentry.get_text())
			except:
				pass
			self.password = passwordentry.get_text()
		self.connectkey_pressed(None)
		if self.conn:
			connectbutton.set_sensitive(False)
			disconnectbutton.set_sensitive(True)
		else:
			connectbutton.set_sensitive(True)
			disconnectbutton.set_sensitive(False)

	def connectkey_pressed(self, event):
		self.user_connect = True
		self.conn = self.connect()
		if self.conn:
			self.conn.do.password(self.password)
		self.iterate_now()

	def disconnectbutton_clicked(self, disconnectbutton, connectbutton):
		self.disconnectkey_pressed(None)
		connectbutton.set_sensitive(True)
		disconnectbutton.set_sensitive(False)

	def disconnectkey_pressed(self, event):
		self.user_connect = False
		if self.conn:
			try:
				self.conn.do.close()
			except:
				pass
		# I'm not sure why this doesn't automatically happen, so
		# we'll do it manually for the time being
		self.browserdata.clear()
		self.playlistsdata.clear()

	def update_status(self):
		try:
			if not self.conn:
				self.conn = self.connect()
				if self.conn:
					self.conn.do.password(self.password)
			if self.conn:
				self.iterate_time = self.iterate_time_when_connected
				self.status = self.conn.do.status()
				try:
					test = self.status.state
				except:
					self.status = None
				self.songinfo = self.conn.do.currentsong()
				if self.status:
					if self.status.repeat == '0':
						self.repeatmenu.set_active(False)
					elif self.status.repeat == '1':
						self.repeatmenu.set_active(True)
					if self.status.random == '0':
						self.shufflemenu.set_active(False)
					elif self.status.random == '1':
						self.shufflemenu.set_active(True)
					if self.status.xfade == '0':
						self.xfade_enabled = False
					else:
						self.xfade_enabled = True
						self.xfade = int(self.status.xfade)
						if self.xfade > 30: self.xfade = 30
			else:
				self.iterate_time = self.iterate_time_when_disconnected
				self.status = None
				self.songinfo = None
		except (mpdclient3.socket.error, EOFError):
			self.prevconn = self.conn
			self.prevstatus = self.status
			self.prevsonginfo = self.songinfo
			self.conn = None
			self.status = None
			self.songinfo = None

	def iterate(self):
		self.update_status()
		self.infowindow_update(update_all=False)

		if self.conn != self.prevconn:
			self.handle_change_conn()
		if self.status != self.prevstatus:
			self.handle_change_status()
		if self.songinfo != self.prevsonginfo:
			self.handle_change_song()

		self.prevconn = self.conn
		self.prevstatus = self.status
		self.prevsonginfo = self.songinfo

		self.iterate_handler = gobject.timeout_add(self.iterate_time, self.iterate) # Repeat ad infitum..

		if self.show_trayicon:
			if HAVE_STATUS_ICON:
				if self.statusicon.is_embedded() and not self.statusicon.get_visible():
					self.initialize_systrayicon()
			elif HAVE_EGG:
				if self.trayicon.get_property('visible') == False:
					self.initialize_systrayicon()

		if self.call_gc_collect:
			gc.collect()
			self.call_gc_collect = False

	def iterate_stop(self):
		try:
			gobject.source_remove(self.iterate_handler)
		except:
			pass

	def iterate_now(self):
		# Since self.iterate_time_when_connected has been
		# slowed down to 500ms, we'll call self.iterate_now() 
		# whenever the user performs an action that requires 
		# updating the client
		self.iterate_stop()
		self.iterate()

	def iterate_status_icon(self):
		# Polls for the users' cursor position to display the custom
		# tooltip window when over the gtk.StatusIcon. We use this
		# instead of self.iterate() in order to poll more often and
		# increase responsiveness.
		if self.show_trayicon:
			if self.statusicon.is_embedded() and self.statusicon.get_visible():
				self.tooltip_show_manually()
		gobject.timeout_add(250, self.iterate_status_icon)

	def on_topwindow_keypress(self, widget, event):
		shortcut = gtk.accelerator_name(event.keyval, event.state)
		shortcut = shortcut.replace("<Mod2>", "")
		# These shortcuts were moved here so that they don't
		# interfere with searching the library
		if shortcut == 'BackSpace':
			self.browse_parent_dir(None)
		elif shortcut == 'Escape':
			if self.minimize_to_systray:
				if HAVE_STATUS_ICON and self.statusicon.is_embedded() and self.statusicon.get_visible():
					self.withdraw_app()
				elif HAVE_EGG and self.trayicon.get_property('visible') == True:
					self.withdraw_app()
		elif shortcut == 'Delete':
			self.remove(None)

	def settings_load(self):
		# Load config:
		conf = ConfigParser.ConfigParser()
		if os.path.exists(os.path.expanduser('~/.config/')) == False:
			os.mkdir(os.path.expanduser('~/.config/'))
		if os.path.exists(os.path.expanduser('~/.config/sonata/')) == False:
			os.mkdir(os.path.expanduser('~/.config/sonata/'))
		if os.path.exists(os.path.expanduser('~/.covers/')) == False:
			os.mkdir(os.path.expanduser('~/.covers/'))
		if os.path.exists(os.path.expanduser('~/.lyrics/')) == False:
			os.mkdir(os.path.expanduser('~/.lyrics/'))
		if os.path.isfile(os.path.expanduser('~/.config/sonata/sonatarc')):
			conf.read(os.path.expanduser('~/.config/sonata/sonatarc'))
		elif os.path.isfile(os.path.expanduser('~/.sonatarc')):
			conf.read(os.path.expanduser('~/.sonatarc'))
			os.remove(os.path.expanduser('~/.sonatarc'))
		if conf.has_option('connection', 'host'):
			self.host = conf.get('connection', 'host')
		if conf.has_option('connection', 'port'):
			self.port = int(conf.get('connection', 'port'))
		if conf.has_option('connection', 'password'):
			self.password = conf.get('connection', 'password')
		if conf.has_option('connection', 'auto'):
			self.autoconnect = conf.getboolean('connection', 'auto')
		if conf.has_option('connection', 'musicdir'):
			self.musicdir = conf.get('connection', 'musicdir')
		if conf.has_option('player', 'x'):
			self.x = conf.getint('player', 'x')
		if conf.has_option('player', 'y'):
			self.y = conf.getint('player', 'y')
		if conf.has_option('player', 'w'):
			self.w = conf.getint('player', 'w')
		if conf.has_option('player', 'h'):
			self.h = conf.getint('player', 'h')
		if conf.has_option('player', 'expanded'):
			self.expanded = conf.getboolean('player', 'expanded')
		if conf.has_option('player', 'withdrawn'):
			self.withdrawn = conf.getboolean('player', 'withdrawn')
		if conf.has_option('player', 'screen'):
			self.screen = conf.getint('player', 'screen')
		if conf.has_option('player', 'covers'):
			self.show_covers = conf.getboolean('player', 'covers')
		if conf.has_option('player', 'stop_on_exit'):
			self.stop_on_exit = conf.getboolean('player', 'stop_on_exit')
		if conf.has_option('player', 'minimize'):
			self.minimize_to_systray = conf.getboolean('player', 'minimize')
		if conf.has_option('player', 'initial_run'):
			self.initial_run = conf.getboolean('player', 'initial_run')
		if conf.has_option('player', 'volume'):
			self.show_volume = conf.getboolean('player', 'volume')
		if conf.has_option('player', 'statusbar'):
			self.show_statusbar = conf.getboolean('player', 'statusbar')
		if conf.has_option('player', 'lyrics'):
			self.show_lyrics = conf.getboolean('player', 'lyrics')
		if conf.has_option('player', 'sticky'):
			self.sticky = conf.getboolean('player', 'sticky')
		if conf.has_option('player', 'ontop'):
			self.ontop = conf.getboolean('player', 'ontop')
		if conf.has_option('player', 'notification'):
			self.show_notification = conf.getboolean('player', 'notification')
		if conf.has_option('player', 'popup_time'):
			self.popup_option = conf.getint('player', 'popup_time')
		if conf.has_option('player', 'update_on_start'):
			self.update_on_start = conf.getboolean('player', 'update_on_start')
		if conf.has_option('player', 'notif_location'):
			self.traytips.notifications_location = conf.getint('player', 'notif_location')
		if conf.has_option('player', 'playback'):
			self.show_playback = conf.getboolean('player', 'playback')
		if conf.has_option('player', 'crossfade'):
			crossfade = conf.getint('player', 'crossfade')
			# Backwards compatibility:
			self.xfade = [1,2,3,5,10,15][crossfade]
		if conf.has_option('player', 'xfade'):
			self.xfade = conf.getint('player', 'xfade')
		if conf.has_option('player', 'xfade_enabled'):
			self.xfade_enabled = conf.getboolean('player', 'xfade_enabled')
		if conf.has_option('player', 'covers_pref'):
			self.covers_pref = conf.getint('player', 'covers_pref')
		if conf.has_option('player', 'use_infofile'):
			self.use_infofile = conf.getboolean('player', 'use_infofile')
		if conf.has_option('player', 'infofile_path'):
			self.infofile_path = conf.get('player', 'infofile_path')
		if conf.has_option('player', 'play_on_activate'):
			self.play_on_activate = conf.getboolean('player', 'play_on_activate')
		if conf.has_option('player', 'trayicon'):
			self.show_trayicon = conf.getboolean('player', 'trayicon')
		if conf.has_option('player', 'view'):
			self.view = conf.getint('player', 'view')
		if conf.has_option('player', 'infowindow_x'):
			self.infowindow_x = conf.getint('player', 'infowindow_x')
		if conf.has_option('player', 'infowindow_y'):
			self.infowindow_y = conf.getint('player', 'infowindow_y')
		if conf.has_option('player', 'infowindow_w'):
			self.infowindow_w = conf.getint('player', 'infowindow_w')
		if conf.has_option('player', 'infowindow_h'):
			self.infowindow_h = conf.getint('player', 'infowindow_h')
		if conf.has_option('format', 'current'):
			self.currentformat = conf.get('format', 'current')
		if conf.has_option('format', 'library'):
			self.libraryformat = conf.get('format', 'library')
		if conf.has_option('format', 'title'):
			self.titleformat = conf.get('format', 'title')
		if conf.has_option('format', 'currsong1'):
			self.currsongformat1 = conf.get('format', 'currsong1')
		if conf.has_option('format', 'currsong2'):
			self.currsongformat2 = conf.get('format', 'currsong2')
		if conf.has_option('streams', 'num_streams'):
			num_streams = conf.getint('streams', 'num_streams')
			self.stream_names = []
			self.stream_uris = []
			for i in range(num_streams):
				self.stream_names.append(conf.get('streams', 'names[' + str(i) + ']'))
				self.stream_uris.append(conf.get('streams', 'uris[' + str(i) + ']'))

	def settings_save(self):
		conf = ConfigParser.ConfigParser()
		conf.add_section('connection')
		conf.set('connection', 'host', self.host)
		conf.set('connection', 'port', self.port)
		conf.set('connection', 'password', self.password)
		conf.set('connection', 'auto', self.autoconnect)
		conf.set('connection', 'musicdir', self.musicdir)
		conf.add_section('player')
		conf.set('player', 'w', self.w)
		conf.set('player', 'h', self.h)
		conf.set('player', 'x', self.x)
		conf.set('player', 'y', self.y)
		conf.set('player', 'expanded', self.expanded)
		conf.set('player', 'withdrawn', self.withdrawn)
		conf.set('player', 'screen', self.screen)
		conf.set('player', 'covers', self.show_covers)
		conf.set('player', 'stop_on_exit', self.stop_on_exit)
		conf.set('player', 'minimize', self.minimize_to_systray)
		conf.set('player', 'initial_run', self.initial_run)
		conf.set('player', 'volume', self.show_volume)
		conf.set('player', 'statusbar', self.show_statusbar)
		conf.set('player', 'lyrics', self.show_lyrics)
		conf.set('player', 'sticky', self.sticky)
		conf.set('player', 'ontop', self.ontop)
		conf.set('player', 'notification', self.show_notification)
		conf.set('player', 'popup_time', self.popup_option)
		conf.set('player', 'update_on_start', self.update_on_start)
		conf.set('player', 'notif_location', self.traytips.notifications_location)
		conf.set('player', 'playback', self.show_playback)
		conf.set('player', 'xfade', self.xfade)
		conf.set('player', 'xfade_enabled', self.xfade_enabled)
		conf.set('player', 'covers_pref', self.covers_pref)
		conf.set('player', 'use_infofile', self.use_infofile)
		conf.set('player', 'infofile_path', self.infofile_path)
		conf.set('player', 'play_on_activate', self.play_on_activate)
		conf.set('player', 'trayicon', self.show_trayicon)
		conf.set('player', 'view', self.view)
		conf.set('player', 'infowindow_x', self.infowindow_x)
		conf.set('player', 'infowindow_y', self.infowindow_y)
		conf.set('player', 'infowindow_w', self.infowindow_w)
		conf.set('player', 'infowindow_h', self.infowindow_h)
		conf.add_section('format')
		conf.set('format', 'current', self.currentformat)
		conf.set('format', 'library', self.libraryformat)
		conf.set('format', 'title', self.titleformat)
		conf.set('format', 'currsong1', self.currsongformat1)
		conf.set('format', 'currsong2', self.currsongformat2)
		conf.add_section('streams')
		conf.set('streams', 'num_streams', len(self.stream_names))
		for i in range(len(self.stream_names)):
			conf.set('streams', 'names[' + str(i) + ']', self.stream_names[i])
			conf.set('streams', 'uris[' + str(i) + ']', self.stream_uris[i])
		conf.write(file(os.path.expanduser('~/.config/sonata/sonatarc'), 'w'))

	def handle_change_conn(self):
		if not self.conn:
			self.ppbutton.set_property('sensitive', False)
			self.stopbutton.set_property('sensitive', False)
			self.prevbutton.set_property('sensitive', False)
			self.nextbutton.set_property('sensitive', False)
			self.volumebutton.set_property('sensitive', False)
			try:
				self.trayimage.set_from_stock('sonata',  gtk.ICON_SIZE_BUTTON)
			except:
				pass
			self.currentdata.clear()
			self.songs = None
		else:
			self.ppbutton.set_property('sensitive', True)
			self.stopbutton.set_property('sensitive', True)
			self.prevbutton.set_property('sensitive', True)
			self.nextbutton.set_property('sensitive', True)
			self.volumebutton.set_property('sensitive', True)
			if self.sonata_loaded:
				self.browse(root='/')
			self.playlists_populate()
			self.on_notebook_page_change(self.notebook, 0, self.notebook.get_current_page())

	def give_widget_focus(self, widget):
		widget.grab_focus()
	
	def streams_edit(self, action):
		model, selected = self.streams_selection.get_selected_rows()
		try:
			streamname = model.get_value(model.get_iter(selected[0]), 1)
			for i in range(len(self.stream_names)):
				if self.stream_names[i] == streamname:
					self.streams_new(action, i)
					return
		except:
			pass

	def streams_new(self, action, stream_num=-1):
		if stream_num > -1:
			edit_mode = True
		else:
			edit_mode = False
		# Prompt user for playlist name:
		dialog = gtk.Dialog(None, self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT, gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
		if edit_mode:
			dialog.set_title(_("Edit Stream"))
		else:
			dialog.set_title(_("New Stream"))
 		hbox = gtk.HBox()
		namelabel = gtk.Label(_('Stream name') + ':')
		hbox.pack_start(namelabel, False, False, 5)
		nameentry = gtk.Entry()
		if edit_mode:
			nameentry.set_text(self.stream_names[stream_num])
		hbox.pack_start(nameentry, True, True, 5)
		hbox2 = gtk.HBox()
		urllabel = gtk.Label(_('Stream URL') + ':')
		hbox2.pack_start(urllabel, False, False, 5)
		urlentry = gtk.Entry()
		if edit_mode:
			urlentry.set_text(self.stream_uris[stream_num])
		hbox2.pack_start(urlentry, True, True, 5)
		self.set_label_widths_equal([namelabel, urllabel])
		dialog.vbox.pack_start(hbox)
		dialog.vbox.pack_start(hbox2)
		dialog.vbox.show_all()
		response = dialog.run()
		if response == gtk.RESPONSE_ACCEPT:
			name = nameentry.get_text()
			uri = urlentry.get_text()
			if len(name) > 0 and len(uri) > 0:
				# Make sure this stream name doesn't already exit:
				i = 0
				for item in self.stream_names:
					# Prevent a name collision in edit_mode..
					if not edit_mode or (edit_mode and i <> stream_num):
						if item == name:
							dialog.destroy()
							# show error here
							error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _("A stream with this name already exists."))
							error_dialog.set_title(_("New Stream"))
							error_dialog.run()
							error_dialog.destroy()
							return
					i = i + 1
				if edit_mode:
					self.stream_names.pop(stream_num)
					self.stream_uris.pop(stream_num)
				self.stream_names.append(name)
				self.stream_uris.append(uri)
				self.streams_populate()
				self.settings_save()
		dialog.destroy()
		self.iterate_now()

	def on_save_playlist(self, action):
		if self.conn:
			# Prompt user for playlist name:
			dialog = gtk.Dialog(_("Save Playlist"), self.window, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT, gtk.STOCK_SAVE, gtk.RESPONSE_ACCEPT))
			hbox = gtk.HBox()
			hbox.pack_start(gtk.Label(_('Playlist name') + ':'), False, False, 5)
			entry = gtk.Entry()
			entry.set_activates_default(True)
			hbox.pack_start(entry, True, True, 5)
			dialog.vbox.pack_start(hbox)
			dialog.set_default_response(gtk.RESPONSE_ACCEPT)
			dialog.vbox.show_all()
			response = dialog.run()
			if response == gtk.RESPONSE_ACCEPT:
				plname = entry.get_text()
				plname = plname.replace("\\", "")
				plname = plname.replace("/", "")
				plname = plname.replace("\"", "")
				# Make sure this playlist doesn't already exit:
				for item in self.conn.do.lsinfo():
					if item.type == 'playlist':
						if item.playlist == plname:
							dialog.destroy()
							# show error here
							error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _("A playlist with this name already exists."))
							error_dialog.set_title(_("Save Playlist"))
							error_dialog.run()
							error_dialog.destroy()
							return
				self.conn.do.save(plname)
				self.playlists_populate()
			dialog.destroy()
			self.iterate_now()

	def playlists_populate(self):
		if self.conn:
			self.playlistsdata.clear()
			playlistinfo = []
			for item in self.conn.do.lsinfo():
				if item.type == 'playlist':
					playlistinfo.append(escape_html(item.playlist))
			playlistinfo.sort(key=lambda x: x.lower()) # Remove case sensitivity
			for item in playlistinfo:
				self.playlistsdata.append([gtk.STOCK_JUSTIFY_FILL, item])

	def streams_populate(self):
		self.streamsdata.clear()
		streamsinfo = []
		for i in range(len(self.stream_names)):
			dict = {}
			dict["name"] = escape_html(self.stream_names[i])
			dict["uri"] = escape_html(self.stream_uris[i])
			streamsinfo.append(dict)
		streamsinfo.sort(key=lambda x: x["name"].lower()) # Remove case sensitivity
		for item in streamsinfo:
			self.streamsdata.append([gtk.STOCK_NETWORK, item["name"], item["uri"]])

	def playlists_key_press(self, widget, event):
		if event.keyval == gtk.gdk.keyval_from_name('Return'):
			self.playlists_activated(widget, widget.get_cursor()[0])
			return True

	def playlists_activated(self, treeview, path, column=0):
		if self.status:
			playid = self.status.playlistlength
		self.add_item(None)
		if self.play_on_activate:
			self.play_item(playid)

	def on_streams_key_press(self, widget, event):
		if event.keyval == gtk.gdk.keyval_from_name('Return'):
			self.on_streams_activated(widget, widget.get_cursor()[0])
			return True

	def on_streams_activated(self, treeview, path, column=0):
		if self.status:
			playid = self.status.playlistlength
		self.add_item(None)
		if self.play_on_activate:
			self.play_item(playid)

	def libraryview_popup(self, button):
		self.librarymenu.popup(None, None, self.libraryview_position_menu, 1, 0)

	def on_libraryview_chosen(self, action):
		prev_view = self.view
		if action.get_name() == 'filesystemview':
			self.view = self.VIEW_FILESYSTEM
		elif action.get_name() == 'artistview':
			self.view = self.VIEW_ARTIST
		elif action.get_name() == 'albumview':
			self.view = self.VIEW_ALBUM
		self.browser.grab_focus()
		if self.view != prev_view:
			self.libraryview_assign_image()
			if self.view == self.VIEW_ARTIST:
				self.view_artist_level = 1
			self.browserposition = {}
			self.browserselectedpath = {}
			try:
				self.browse()
				if len(self.browserdata) > 0:
					self.browser_selection.unselect_range((0,), (len(self.browserdata)-1,))
			except:
				pass
			gobject.idle_add(self.browser.scroll_to_point, 0, 0)
	
	def libraryview_assign_image(self):
		if self.view == self.VIEW_FILESYSTEM:
			self.libraryview.set_image(gtk.image_new_from_stock(gtk.STOCK_HARDDISK, gtk.ICON_SIZE_MENU))
		elif self.view == self.VIEW_ARTIST:
			self.libraryview.set_image(gtk.image_new_from_stock('artist', gtk.ICON_SIZE_MENU))
		elif self.view == self.VIEW_ALBUM:
			self.libraryview.set_image(gtk.image_new_from_stock('album', gtk.ICON_SIZE_MENU))

	def browse(self, widget=None, root='/'):
		# Populates the library list with entries starting at root
		if not self.conn:
			return

		# Handle special cases (i.e. if we are browsing to a song or
		# if the path has disappeared)
		lsinfo = self.conn.do.lsinfo(root)
		while lsinfo == []:
			if self.conn.do.listallinfo(root):
				# Info exists if we try to browse to a song
				if self.status:
					playid = self.status.playlistlength
				self.add_item(self.browser)
				if self.play_on_activate:
					self.play_item(playid)
				return
			elif self.view == self.VIEW_ARTIST:
				if self.view_artist_level == 1:
					break
				elif self.view_artist_level == 2:
					if len(self.browse_search_artist(root)) == 0:
						# Back up and try the parent
						self.view_artist_level = self.view_artist_level - 1
					else:
						break
				elif self.view_artist_level == 3:
					(album, year) = self.browse_parse_albumview_path(root)
					if len(self.browse_search_album_with_artist_and_year(self.view_artist_artist, album, year)) == 0:
						# Back up and try the parent
						self.view_artist_level = self.view_artist_level - 1
						root = self.view_artist_artist
					else:
						break
			elif self.view == self.VIEW_FILESYSTEM:
				if root == '/':
					# Nothing in the library at all
					return
				else:
					# Back up and try the parent
					root = '/'.join(root.split('/')[:-1]) or '/'
			else:
				if len(self.browse_search_album(root)) == 0:
					root = "/"
					break
				else:
					break
			lsinfo = self.conn.do.lsinfo(root)
				
		prev_selection = []
		prev_selection_root = False
		prev_selection_parent = False
		if (self.view != self.VIEW_ARTIST and root == self.browser.wd) or (self.view == self.VIEW_ARTIST and self.view_artist_level == self.view_artist_level_prev):
			# This will happen when the database is updated. So, lets save
			# the current selection in order to try to re-select it after
			# the update is over.
			model, selected = self.browser_selection.get_selected_rows()
			for path in selected:
				if model.get_value(model.get_iter(path), 2) == "/":
					prev_selection_root = True
				elif model.get_value(model.get_iter(path), 2) == "..":
					prev_selection_parent = True
				else:
					prev_selection.append(model.get_value(model.get_iter(path), 1))
			self.browserposition[self.browser.wd] = self.browser.get_visible_rect()[1]
			path_updated = True
		else:
			path_updated = False

		self.root = root
		# The logic below is more consistent with, e.g., thunar
		if (self.view != self.VIEW_ARTIST and len(root) > len(self.browser.wd)) or (self.view == self.VIEW_ARTIST and self.view_artist_level > self.view_artist_level_prev):
			# Save position and row for where we just were if we've
			# navigated into a sub-directory:
			self.browserposition[self.browser.wd] = self.browser.get_visible_rect()[1]
			model, rows = self.browser_selection.get_selected_rows()
			if len(rows) > 0:
				value_for_selection = self.browserdata.get_value(self.browserdata.get_iter(rows[0]), 2)
				if value_for_selection != ".." and value_for_selection != "/":
					self.browserselectedpath[self.browser.wd] = rows[0]
		elif (self.view != self.VIEW_ARTIST and root != self.browser.wd) or (self.view == self.VIEW_ARTIST and self.view_artist_level != self.view_artist_level_prev):
			# If we've navigated to a parent directory, don't save
			# anything so that the user will enter that subdirectory
			# again at the top position with nothing selected
			self.browserposition[self.browser.wd] = 0
			self.browserselectedpath[self.browser.wd] = None

		self.browser.wd = root
		self.browser.freeze_child_notify()
		self.browserdata.clear()
		if self.view == self.VIEW_FILESYSTEM:
			if self.root != '/':
				self.browserdata.append([gtk.STOCK_HARDDISK, '/', '/'])
				self.browserdata.append([gtk.STOCK_OPEN, '..', '..'])
			for item in lsinfo:
				if item.type == 'directory':
					name = item.directory.split('/')[-1]
					self.browserdata.append([gtk.STOCK_OPEN, item.directory, escape_html(name)])
				elif item.type == 'file':
					self.browserdata.append(['sonata', item.file, self.parse_formatting(self.libraryformat, item, True)])
		elif self.view == self.VIEW_ARTIST:
			if self.view_artist_level == 1:
				self.view_artist_artist = ''
				self.view_artist_album = ''
				root = '/'
				if self.artists_root is None:
					self.artists_root = []
					for item in self.conn.do.list('artist'):
						self.artists_root.append(item.artist)
					(self.artists_root, i) = remove_list_duplicates(self.artists_root, [], False)
					self.artists_root.sort(locale.strcoll)
				for artist in self.artists_root:
					self.browserdata.append(['artist', artist, escape_html(artist)])
			elif self.view_artist_level == 2:
				self.browserdata.append([gtk.STOCK_HARDDISK, '/', '/'])
				self.browserdata.append([gtk.STOCK_OPEN, '..', '..'])
				if self.root != "..":
					self.view_artist_artist = self.root
				albums = []
				songs = []
				years = []
				for item in self.browse_search_artist(self.view_artist_artist):
					try:
						albums.append(item.album)
						years.append(getattr(item, 'date', '0').split('-')[0].zfill(4))
					except:
						songs.append(item)
				(albums, years) = remove_list_duplicates(albums, years, False)
				for itemnum in range(len(albums)):
					self.browserdata.append(['album', years[itemnum] + albums[itemnum], escape_html(years[itemnum] + ' - ' + albums[itemnum])])
				for song in songs:
					self.browserdata.append(['sonata', song.file, self.parse_formatting(self.libraryformat, song, True)])
			else:
				self.browserdata.append([gtk.STOCK_HARDDISK, '/', '/'])
				self.browserdata.append([gtk.STOCK_OPEN, '..', '..'])
				(self.view_artist_album, year) = self.browse_parse_albumview_path(root)
				for item in self.browse_search_album_with_artist_and_year(self.view_artist_artist, self.view_artist_album, year):
					self.browserdata.append(['sonata', item.file, self.parse_formatting(self.libraryformat, item, True)])
		elif self.view == self.VIEW_ALBUM:
			items = []
			if self.root == '/':
				if self.albums_root is None:
					self.albums_root = []
					for item in self.conn.do.list('album'):
						self.albums_root.append(item.album)
					(self.albums_root, i) = remove_list_duplicates(self.albums_root, [], False)
					self.albums_root.sort(locale.strcoll)
				for item in self.albums_root:
					self.browserdata.append(['album', item, escape_html(item)])
			else:
				self.browserdata.append([gtk.STOCK_HARDDISK, '/', '/'])
				self.browserdata.append([gtk.STOCK_OPEN, '..', '..'])
				for item in self.browse_search_album(root):
					self.browserdata.append(['sonata', item.file, self.parse_formatting(self.libraryformat, item, True)])
		self.browser.thaw_child_notify()

		# Scroll back to set view for current dir:
		self.browser.realize()
		gobject.idle_add(self.browser_set_view, not path_updated)
		if len(prev_selection) > 0 or prev_selection_root or prev_selection_parent:
			self.browser_retain_preupdate_selection(prev_selection, prev_selection_root, prev_selection_parent)
			
		self.view_artist_level_prev = self.view_artist_level
	
	def browse_search_album(self, album):
		# Return songs of the specified album. Sorts by track number
		list = []
		for item in self.conn.do.search('album', album):
			# Make sure it's an exact match:
			if album.lower() == item.album.lower():
				list.append(item)
		list.sort(key=lambda x: int(getattr(x, 'track', '0').split('/')[0]))
		return list
		
	def browse_search_artist(self, artist):
		# Return songs of the specified artist. Sorts by year
		list = []
		for item in self.conn.do.search('artist', artist):
			# Make sure it's an exact match:
			if artist.lower() == item.artist.lower():
				list.append(item)
		list.sort(key=lambda x: getattr(x, 'date', '0').split('-')[0].zfill(4))
		return list
		
	def browse_search_album_with_artist_and_year(self, artist, album, year):
		# Return songs of specified album, artist, and year. Sorts by track
		# If year is None, skips that requirement
		list = []
		for item in self.conn.do.search('album', album, 'artist', artist):
			# Make sure it's an exact match:
			if artist.lower() == item.artist.lower() and album.lower() == item.album.lower():
				if year is None:
					list.append(item)
				else:
					# Make sure it also matches the year:
					if year != '0000' and item.has_key('date'):
						# Only show songs whose years match the year var:
						try:
							if int(item.date.split('-')[0]) == int(year):
								list.append(item)
						except:
							pass
					elif not item.has_key('date'):
						# Only show songs that have no year specified:
						list.append(item)
		list.sort(key=lambda x: int(getattr(x, 'track', '0').split('/')[0]))
		return list
		
	def browser_retain_preupdate_selection(self, prev_selection, prev_selection_root, prev_selection_parent):
		# Unselect everything:
		if len(self.browserdata) > 0:
			self.browser_selection.unselect_range((0,), (len(self.browserdata)-1,))
		# Now attempt to retain the selection from before the update:
		for value in prev_selection:
			for rownum in range(len(self.browserdata)):
				if value == self.browserdata.get_value(self.browserdata.get_iter((rownum,)), 1):
					self.browser_selection.select_path((rownum,))
					break
		if prev_selection_root:
			self.browser_selection.select_path((0,))
		if prev_selection_parent:
			self.browser_selection.select_path((1,))

	def browser_set_view(self, select_items=True):
		# select_items should be false if the same directory has merely
		# been refreshed (updated)
		try:
			if self.browser.wd in self.browserposition:
				self.browser.scroll_to_point(0, self.browserposition[self.browser.wd])
			else:
				self.browser.scroll_to_point(0, 0)
		except:
			self.browser.scroll_to_point(0, 0)

		# Select and focus previously selected item if it's not ".." or "/"
		if select_items:
 			if self.view == self.VIEW_ARTIST:
				if self.view_artist_level == 1:
					item = "/"
				elif self.view_artist_level == 2:
					item = self.view_artist_artist
				else:
					return
			else:
				item = self.browser.wd
			if item in self.browserselectedpath:
				try:
					if self.browserselectedpath[item]:
						self.browser_selection.select_path(self.browserselectedpath[item])
						self.browser.grab_focus()
				except:
					pass

	def browse_parse_albumview_path(self, path):
		# The first four chars are used to store the year. Returns
		# a tuple.
		year = path[:4]
		album = path[4:]
		return (album, year)

	def parse_formatting_return_substrings(self, format):
		substrings = []
		begin_pos = format.find("{")
		end_pos = -1
		while begin_pos > -1:
			if begin_pos > end_pos + 1:
				substrings.append(format[end_pos+1:begin_pos])
			end_pos = format.find("}", begin_pos)
			substrings.append(format[begin_pos:end_pos+1])
			begin_pos = format.find("{", end_pos)
		if end_pos+1 < len(format):
			substrings.append(format[end_pos+1:len(format)])
		return substrings

	def parse_formatting_for_substring(self, subformat, item, wintitle):
		text = subformat
		if subformat.startswith("{") and subformat.endswith("}"):
			has_brackets = True
		else:
			has_brackets = False
		if "%A" in text:
			try:
				text = text.replace("%A", item.artist)
			except:
				if not has_brackets: text = text.replace("%A", _('Unknown'))
				else: return ""
		if "%B" in text:
			try:
				text = text.replace("%B", item.album)
			except:
				if not has_brackets: text = text.replace("%B", _('Unknown'))
				else: return ""
		if "%S" in text:
			try:
				text = text.replace("%S", item.title)
			except:
				if not has_brackets: return self.filename_or_fullpath(item.file)
				else: return ""
		if "%T" in text:
			try:
				text = text.replace("%T", str(int(item.track.split('/')[0])))
			except:
				if not has_brackets: text = text.replace("%T", "0")
				else: return ""
		if "%G" in text:
			try:
				text = text.replace("%G", item.genre)
			except:
				if not has_brackets: text = text.replace("%G", _('Unknown'))
				else: return ""
		if "%Y" in text:
			try:
				text = text.replace("%Y", item.date)
			except:
				if not has_brackets: text = text.replace("%Y", "?")
				else: return ""
		if "%F" in text:
			text = text.replace("%F", item.file)
		if "%P" in text:
			text = text.replace("%P", item.file.split('/')[-1])
		if "%L" in text:
			try:
				time = convert_time(int(item.time))
				text = text.replace("%L", time)
			except:
				if not has_brackets: text = text.replace("%L", "?")
				else: return ""
		if wintitle:
			if "%E" in text:
				try:
					at, length = [int(c) for c in self.status.time.split(':')]
					at_time = convert_time(at)
					text = text.replace("%E", at_time)
				except:
					if not has_brackets: text = text.replace("%E", "?")
					else: return ""
		if text.startswith("{") and text.endswith("}"):
			return text[1:len(text)-1]
		else:
			return text

	def parse_formatting(self, format, item, use_escape_html, wintitle=False):
		if self.song_has_metadata(item):
			substrings = self.parse_formatting_return_substrings(format)
			text = ""
			for sub in substrings:
				text = text + str(self.parse_formatting_for_substring(sub, item, wintitle))
			if use_escape_html:
				return escape_html(text)
			else:
				return text
		else:
			if use_escape_html:
				return escape_html(self.filename_or_fullpath(item.file))
			else:
				return self.filename_or_fullpath(item.file)

	def filename_or_fullpath(self, file):
		if len(file.split('/')[-1]) == 0 or file[:7] == 'http://' or file[:6] == 'ftp://':
			# Use path and file name:
			return escape_html(file)
		else:
			# Use file name only:
			return escape_html(file.split('/')[-1])

	def song_has_metadata(self, item):
		if item.has_key('title') or item.has_key('artist'):
			return True
		return False

	def on_browser_key_press(self, widget, event):
		if event.keyval == gtk.gdk.keyval_from_name('Return'):
			self.on_browse_row(widget, widget.get_cursor()[0])
			return True

	def on_browse_row(self, widget, path, column=0):
		if path is None: 
			# Default to last item in selection:
			model, selected = self.browser_selection.get_selected_rows()
			if len(selected) >=1:
				path = (len(selected)-1,)
			else:
				path = (0,)
		value = self.browserdata.get_value(self.browserdata.get_iter(path), 1)
		if value == "..":
			self.browse_parent_dir(None)
		else:
			if self.view == self.VIEW_ARTIST:
				if value == "/":
					self.view_artist_level = 1
				else:
					self.view_artist_level = self.view_artist_level + 1
			self.browse(None, value)

	def browse_parent_dir(self, action):
		if self.notebook.get_current_page() == self.TAB_LIBRARY:
			if self.browser.is_focus():
				if self.view == self.VIEW_ARTIST:
					if self.view_artist_level > 1:
						self.view_artist_level = self.view_artist_level - 1
					if self.view_artist_level == 1:
						value = "/"
					else:
						value = self.view_artist_artist
				else:
					value = '/'.join(self.browser.wd.split('/')[:-1]) or '/'
				self.browse(None, value)

	def on_treeview_selection_changed(self, *args):
		self.set_menu_contextual_items_visible()

	def on_browser_button_press(self, widget, event):
		self.volume_hide()
		if event.button == 3:
			self.set_menu_contextual_items_visible()
			self.mainmenu.popup(None, None, None, event.button, event.time)
			# Don't change the selection for a right-click. This
			# will allow the user to select multiple rows and then
			# right-click (instead of right-clicking and having
			# the current selection change to the current row)
			if self.browser_selection.count_selected_rows() > 1:
				return True

	def playlists_button_press(self, widget, event):
		self.volume_hide()
		if event.button == 3:
			self.set_menu_contextual_items_visible()
			self.mainmenu.popup(None, None, None, event.button, event.time)
			# Don't change the selection for a right-click. This
			# will allow the user to select multiple rows and then
			# right-click (instead of right-clicking and having
			# the current selection change to the current row)
			if self.playlists_selection.count_selected_rows() > 1:
				return True

	def streams_button_press(self, widget, event):
		self.volume_hide()
		if event.button == 3:
			self.set_menu_contextual_items_visible()
			self.mainmenu.popup(None, None, None, event.button, event.time)
			# Don't change the selection for a right-click. This
			# will allow the user to select multiple rows and then
			# right-click (instead of right-clicking and having
			# the current selection change to the current row)
			if self.streams_selection.count_selected_rows() > 1:
				return True

	def play_item(self, playid):
		if self.conn:
			self.conn.do.play(int(playid))
	
	def browser_get_selected_items_recursive(self, return_root):
		# If return_root=True, return main directories whenever possible
		# instead of individual songs in order to reduce the number of
		# mpd calls we need to make. We won't want this behavior in some
		# instances, like when we want all end files for editing tags
		items = []
		model, selected = self.browser_selection.get_selected_rows()
		if self.view == self.VIEW_FILESYSTEM or self.search_mode_enabled():
			if return_root and not self.search_mode_enabled() and ((self.root == "/" and len(selected) == len(model)) or (self.root != "/" and len(selected) >= len(model)-2)):
				# Everything selected, this is faster..
				items.append(self.root)
			else:
				for path in selected:
					while gtk.events_pending():
						gtk.main_iteration()
					if model.get_value(model.get_iter(path), 2) != "/" and model.get_value(model.get_iter(path), 2) != "..":
						if model.get_value(model.get_iter(path), 0) == gtk.STOCK_OPEN:
							if return_root and not self.search_mode_enabled():
								items.append(model.get_value(model.get_iter(path), 1))
							else:
								for item in self.conn.do.listall(model.get_value(model.get_iter(path), 1)):
									if item.type == 'file':
										items.append(item.file)
						else:
							items.append(model.get_value(model.get_iter(path), 1))
		elif self.view == self.VIEW_ARTIST:
			for path in selected:
				while gtk.events_pending():
					gtk.main_iteration()
				if model.get_value(model.get_iter(path), 2) != "/" and model.get_value(model.get_iter(path), 2) != "..":
					if self.view_artist_level == 1:
						for item in self.browse_search_artist(model.get_value(model.get_iter(path), 1)):
							items.append(item.file)
					else:
						if model.get_value(model.get_iter(path), 0) == 'album':
							(album, year) = self.browse_parse_albumview_path(model.get_value(model.get_iter(path), 1))
							for item in self.browse_search_album_with_artist_and_year(self.view_artist_artist, album, year):
								items.append(item.file)
						else:
							items.append(model.get_value(model.get_iter(path), 1))
		elif self.view == self.VIEW_ALBUM:
			for path in selected:
				while gtk.events_pending():
					gtk.main_iteration()
				if model.get_value(model.get_iter(path), 2) != "/" and model.get_value(model.get_iter(path), 2) != "..":
					if self.root == "/":
						for item in self.browse_search_album(model.get_value(model.get_iter(path), 1)):
							items.append(item.file)
					else:
						items.append(model.get_value(model.get_iter(path), 1))
		# Make sure we don't have any EXACT duplicates:
		(items, i) = remove_list_duplicates(items, [], True)
		return items

	def add_item(self, widget):
		if self.conn:
			if self.notebook.get_current_page() == self.TAB_LIBRARY:
				items = self.browser_get_selected_items_recursive(True)
				for item in items:
					self.conn.do.add(item)
			elif self.notebook.get_current_page() == self.TAB_PLAYLISTS:
				model, selected = self.playlists_selection.get_selected_rows()
				for path in selected:
					self.conn.do.load(model.get_value(model.get_iter(path), 1))
			elif self.notebook.get_current_page() == self.TAB_STREAMS:
				model, selected = self.streams_selection.get_selected_rows()
				for path in selected:
					item = model.get_value(model.get_iter(path), 2)
					self.stream_parse_and_add(item)
			self.iterate_now()

	def stream_parse_and_add(self, item):
		# We need to do different things depending on if this is 
		# a normal stream, pls, m3u, etc..
		# Note that we will only download the first 4000 bytes
		while gtk.events_pending():
			gtk.main_iteration()
		f = None
		try:
			request = urllib2.Request(item)
			opener = urllib2.build_opener()
			f = opener.open(request).read(4000)
		except:
			try:
				request = urllib2.Request("http://" + item)
				opener = urllib2.build_opener()
				f = opener.open(request).read(4000)
			except:
				try:
					request = urllib2.Request("file://" + item)
					opener = urllib2.build_opener()
					f = opener.open(request).read(4000)
				except:
					pass
		while gtk.events_pending():
			gtk.main_iteration()
		if f:
			if is_binary(f):
				# Binary file, just add it:
				self.conn.do.add(item)
			else:
				if "[playlist]" in f:
					# pls:
					self.stream_parse_pls(f)
				elif "#EXTM3U" in f:
					# extended m3u:
					self.stream_parse_m3u(f)
				elif "http://" in f:
					# m3u or generic list:
					self.stream_parse_m3u(f)
				else:
					# Something else..
					self.conn.do.add(item)
		else:
			# Hopefully just a regular stream, try to add it:
			self.conn.do.add(item)

	def stream_parse_pls(self, f):
		lines = f.split("\n")
		for line in lines:
			line = line.replace('\r','')
			delim = line.find("=")+1
			if delim > 0:
				line = line[delim:]
				if len(line) > 7 and line[0:7] == 'http://':
					self.conn.do.add(line)
				elif len(line) > 6 and line[0:6] == 'ftp://':
					self.conn.do.add(line)

	def stream_parse_m3u(self, f):
		lines = f.split("\n")
		for line in lines:
			line = line.replace('\r','')
			if len(line) > 7 and line[0:7] == 'http://':
				self.conn.do.add(line)
			elif len(line) > 6 and line[0:6] == 'ftp://':
				self.conn.do.add(line)

	def replace_item(self, widget):
		play_after_replace = False
		if self.status and self.status.state == 'play':
			play_after_replace = True
		# Only clear if an item is selected:
		if self.notebook.get_current_page() == self.TAB_LIBRARY:
			num_selected = self.browser_selection.count_selected_rows()
		elif self.notebook.get_current_page() == self.TAB_PLAYLISTS:
			num_selected = self.playlists_selection.count_selected_rows()
		elif self.notebook.get_current_page() == self.TAB_STREAMS:
			num_selected = self.streams_selection.count_selected_rows()
		if num_selected == 0:
			return
		self.clear(None)
		self.add_item(widget)
		if play_after_replace and self.conn:
			# Play first song:
			try:
				iter = self.currentdata.get_iter((0,0))
				self.conn.do.playid(self.currentdata.get_value(iter, 0))
			except:
				pass
		self.iterate_now()
	
	def libraryview_position_menu(self, menu):
		x, y, width, height = self.libraryview.get_allocation()
		return (self.x + x, self.y + y + height, True)

	def position_menu(self, menu):
		if self.expanded:
			x, y, width, height = self.current.get_allocation()
			# Find first selected visible row and popup the menu
			# from there
			i = 0
			row_found = False
			row_y = 0
			if self.notebook.get_current_page() == self.TAB_CURRENT:
				widget = self.current
				column = self.currentcolumn
			elif self.notebook.get_current_page() == self.TAB_LIBRARY:
				widget = self.browser
				column = self.browsercolumn
			elif self.notebook.get_current_page() == self.TAB_PLAYLISTS:
				widget = self.playlists
				column = self.playlistscolumn
			elif self.notebook.get_current_page() == self.TAB_STREAMS:
				widget = self.streams
				column = self.streamscolumn
			rows = widget.get_selection().get_selected_rows()[1]
			visible_rect = widget.get_visible_rect()
			while not row_found and i < len(rows):
				row = rows[i]
				row_rect = widget.get_background_area(row, column)
				if row_rect.y + row_rect.height <= visible_rect.height and row_rect.y >= 0:
					row_found = True
					row_y = row_rect.y + 30
				i += 1
			return (self.x + width - 150, self.y + y + row_y, True)
		else:
			return (self.x + 250, self.y + 80, True)

	def menukey_press(self, action):
		self.mainmenu.popup(None, None, self.position_menu, 0, 0)

	def handle_change_status(self):
		if self.status == None:
			# clean up and bail out
			self.update_progressbar()
			self.update_cursong()
			self.update_wintitle()
			self.update_album_art()
			self.update_statusbar()
			return

		# Display current playlist
		if self.prevstatus == None or self.prevstatus.playlist != self.status.playlist:
			self.update_playlist()

		# Update progress frequently if we're playing
		if self.status.state in ['play', 'pause']:
			self.update_progressbar()

		# If elapsed time is shown in the window title, we need to update more often:
		if "%E" in self.titleformat:
			self.update_wintitle()

		# If state changes
		if self.prevstatus == None or self.prevstatus.state != self.status.state:

			# Update progressbar if the state changes too
			self.update_progressbar()
			self.update_cursong()
			self.update_wintitle()
			self.infowindow_update(update_all=True)
			if self.status.state == 'stop':
				self.ppbutton.set_image(gtk.image_new_from_stock(gtk.STOCK_MEDIA_PLAY, gtk.ICON_SIZE_BUTTON))
				self.ppbutton.get_child().get_child().get_children()[1].set_text('')
				self.UIManager.get_widget('/traymenu/playmenu').show()
				self.UIManager.get_widget('/traymenu/pausemenu').hide()
			elif self.status.state == 'pause':
				self.ppbutton.set_image(gtk.image_new_from_stock(gtk.STOCK_MEDIA_PLAY, gtk.ICON_SIZE_BUTTON))
				self.ppbutton.get_child().get_child().get_children()[1].set_text('')
				self.UIManager.get_widget('/traymenu/playmenu').show()
				self.UIManager.get_widget('/traymenu/pausemenu').hide()
			elif self.status.state == 'play':
				self.ppbutton.set_image(gtk.image_new_from_stock(gtk.STOCK_MEDIA_PAUSE, gtk.ICON_SIZE_BUTTON))
				self.ppbutton.get_child().get_child().get_children()[1].set_text('')
				self.UIManager.get_widget('/traymenu/playmenu').hide()
				self.UIManager.get_widget('/traymenu/pausemenu').show()
				if self.prevstatus != None:
					if self.prevstatus.state == 'pause':
						# Forces the notification to popup if specified
						self.labelnotify()
			self.update_album_art()
			if self.status.state in ['play', 'pause']:
				self.keep_song_visible_in_list()

		if self.prevstatus is None or self.status.volume != self.prevstatus.volume:
			try:
				self.volumescale.get_adjustment().set_value(int(self.status.volume))
				if int(self.status.volume) == 0:
					self.volumebutton.set_image(gtk.image_new_from_icon_name("stock_volume-mute", VOLUME_ICON_SIZE))
				elif int(self.status.volume) < 30:
					self.volumebutton.set_image(gtk.image_new_from_icon_name("stock_volume-min", VOLUME_ICON_SIZE))
				elif int(self.status.volume) <= 70:
					self.volumebutton.set_image(gtk.image_new_from_icon_name("stock_volume-med", VOLUME_ICON_SIZE))
				else:
					self.volumebutton.set_image(gtk.image_new_from_icon_name("stock_volume-max", VOLUME_ICON_SIZE))
			except:
				pass

		if self.conn:
			if self.prevstatus == None or self.prevstatus.get('updating_db', 0) != self.status.get('updating_db', 0):
				if not (self.status and self.status.get('updating_db', 0)):
					# Resetting albums_root and artists_root to None will cause
					# the two lists to update to the new contents
					self.albums_root = None
					self.artists_root = None
					# Now update the library and playlist tabs
					self.browse(root=self.root)
					self.playlists_populate()

	def handle_change_song(self):
		self.unbold_boldrow(self.prev_boldrow)

		if self.status and self.status.has_key('song'):
			row = int(self.status.song)
			self.boldrow(row)
			if not self.prevsonginfo or self.songinfo.file != self.prevsonginfo.file:
				self.keep_song_visible_in_list()
			self.prev_boldrow = row

		self.update_cursong()
		self.update_wintitle()
		self.update_album_art()
		self.infowindow_update(update_all=True)

	def boldrow(self, row):
		if row > -1:
			try:
				self.currentdata[row][1] = make_bold(self.currentdata[row][1])
			except:
				pass

	def unbold_boldrow(self, row):
		if row > -1:
			try:
				self.currentdata[row][1] = make_unbold(self.currentdata[row][1])
			except:
				pass

	def update_progressbar(self):
		if self.conn and self.status and self.status.state in ['play', 'pause']:
			at, length = [float(c) for c in self.status.time.split(':')]
			try:
				self.progressbar.set_fraction(at/length)
			except:
				self.progressbar.set_fraction(0)
		else:
			self.progressbar.set_fraction(0)
		if self.conn:
			if self.status and self.status.state in ['play', 'pause']:
				at, length = [int(c) for c in self.status.time.split(':')]
				at_time = convert_time(at)
				try:
					time = convert_time(int(self.songinfo.time))
					self.progressbar.set_text(at_time + " / " + time)
				except:
					self.progressbar.set_text(at_time)
			else:
				self.progressbar.set_text(' ')
		else:
			self.progressbar.set_text(_('Not Connected'))
		return

	def update_statusbar(self):
		if self.conn and self.status and self.show_statusbar:
			try:
				hours = None
				mins = None
				total_time = convert_time(self.total_time)
				try:
					mins = total_time.split(":")[-2]
					hours = total_time.split(":")[-3]
				except:
					pass
				if mins:
					if mins.startswith('0') and len(mins) > 1:
						mins = mins[1:]
					mins_text = gettext.ngettext('minute', 'minutes', int(mins))
				if hours:
					if hours.startswith('0'):
						hours = hours[1:]
					hours_text = gettext.ngettext('hour and', 'hours and', int(hours))
				# Show text:
				songs_text = gettext.ngettext('song', 'songs', int(self.status.playlistlength))
				if hours:
					status_text = str(self.status.playlistlength) + ' ' + songs_text + ', ' + hours + ' ' + hours_text + ' ' + mins + ' ' + mins_text
				elif mins:
					status_text = str(self.status.playlistlength) + ' ' + songs_text + ', ' + mins + ' ' + mins_text
				else:
					status_text = ""
				self.statusbar.push(self.statusbar.get_context_id(""), status_text)
			except:
				self.statusbar.push(self.statusbar.get_context_id(""), "")
		elif self.show_statusbar:
			self.statusbar.push(self.statusbar.get_context_id(""), "")

	def update_cursong(self):
		if self.conn and self.status and self.status.state in ['play', 'pause']:
			# We must show the trayprogressbar and trayalbumeventbox
			# before changing self.cursonglabel (and consequently calling
			# self.labelnotify()) in order to ensure that the notification
			# popup will have the correct height when being displayed for
			# the first time after a stopped state.
			self.trayprogressbar.show()
			if self.show_covers:
				self.trayalbumeventbox.show()
				self.trayalbumimage2.show()
			newlabelfound = False
			newlabel = ""
			newlabel_tray_gtk = ""
			if len(self.currsongformat1) > 0:
				newlabel = newlabel + '<big><b>' + self.parse_formatting(self.currsongformat1, self.songinfo, True) + ' </b></big>'
				newlabel_tray_gtk = newlabel_tray_gtk + self.parse_formatting(self.currsongformat1, self.songinfo, True)
			else:
				newlabel = newlabel + '<big><b> </b></big>'
			if len(self.currsongformat2) > 0:
				newlabel = newlabel + '\n<small>' + self.parse_formatting(self.currsongformat2, self.songinfo, True) + ' </small>'
				newlabel_tray_gtk = newlabel_tray_gtk + '\n' + self.parse_formatting(self.currsongformat2, self.songinfo, True)
			else:
				newlabel = newlabel + '\n<small> </small>'
				newlabel_tray_gtk = newlabel_tray_gtk + '\n '
			newlabel_tray_egg = newlabel
			if newlabel != self.cursonglabel.get_label():
				self.cursonglabel.set_markup(newlabel)
			if newlabel_tray_egg != self.traycursonglabel.get_label():
				self.traycursonglabel.set_markup(newlabel_tray_egg)
		else:
			if self.expanded:
				self.cursonglabel.set_markup('<big><b>' + _('Stopped') + '</b></big>\n<small>' + _('Click to collapse') + '</small>')
			else:
				self.cursonglabel.set_markup('<big><b>' + _('Stopped') + '</b></big>\n<small>' + _('Click to expand') + '</small>')
			if not self.conn:
				self.traycursonglabel.set_label(_('Not connected'))
			else:
				self.traycursonglabel.set_label(_('Stopped'))
			self.trayprogressbar.hide()
			self.trayalbumeventbox.hide()
			self.trayalbumimage2.hide()
		self.update_infofile()

	def update_wintitle(self):
		if self.window_owner:
			if self.conn and self.status and self.status.state in ['play', 'pause']:
				self.window.set_property('title', self.parse_formatting(self.titleformat, self.songinfo, False, True))
			else:
				self.window.set_property('title', 'Sonata')

	def update_playlist(self):
		if self.conn:
			try:
				prev_songs = self.songs
			except:
				prev_songs = None
			self.songs = self.conn.do.playlistinfo()
			all_files_unchanged = self.playlist_files_unchanged(prev_songs)
			self.total_time = 0
			self.current.freeze_child_notify()
			# Only clear and update the entire list if the items are different
			# than before. If they are the same, merely update the attributes
			# so that the treeview visible_rect is retained.
			if not all_files_unchanged:
				self.currentdata.clear()
				self.current.set_model(None)
			for i in range(len(self.songs)):
				track = self.songs[i]
				item = self.parse_formatting(self.currentformat, track, True)
				try:
					self.total_time = self.total_time + int(track.time)
				except:
					pass
				if all_files_unchanged:
					try:
						iter = self.currentdata.get_iter((i, ))
						self.currentdata.set(iter, 0, int(track.id), 1, item)
					except:
						pass
				else:
					self.currentdata.append([int(track.id), item])
			if not all_files_unchanged:
				if self.status.state in ['play', 'pause']:
					self.keep_song_visible_in_list()
				self.current.set_model(self.currentdata)
			if self.songinfo.has_key('pos'):
				currsong = int(self.songinfo.pos)
				self.boldrow(currsong)
				self.prev_boldrow = currsong
			self.current.thaw_child_notify()
			self.update_statusbar()
			self.change_cursor(None)

	def playlist_files_unchanged(self, prev_songs):
		# Go through each playlist object and check if the current and previous
		# filenames match:
		if prev_songs == None:
			return False
		if len(prev_songs) != len(self.songs):
			return False
		for i in range(len(self.songs)):
			if self.songs[i].file != prev_songs[i].file:
				return False
		return True

	def keep_song_visible_in_list(self):
		if self.expander.get_expanded() and len(self.currentdata)>0:
			try:
				row = self.songinfo.pos
				visible_rect = self.current.get_visible_rect()
				row_rect = self.current.get_background_area(row, self.currentcolumn)
				if row_rect.y + row_rect.height > visible_rect.height:
					top_coord = (row_rect.y + row_rect.height - visible_rect.height) + visible_rect.y
					self.current.scroll_to_point(-1, top_coord)
				elif row_rect.y < 0:
					self.current.scroll_to_cell(row)
			except:
				pass

	def update_album_art(self):
		self.stop_art_update = True
		thread = threading.Thread(target=self.update_album_art2)
		thread.setDaemon(True)
		thread.start()

	def set_tooltip_art(self, pix):
		pix1 = pix.subpixbuf(0, 0, 51, 77)
		pix2 = pix.subpixbuf(51, 0, 26, 77)
		self.trayalbumimage1.set_from_pixbuf(pix1)
		self.trayalbumimage2.set_from_pixbuf(pix2)
		del pix1
		del pix2

	def update_album_art2(self):
		self.stop_art_update = False
		if not self.show_covers:
			return
		if self.conn and self.status and self.status.state in ['play', 'pause']:
			artist = getattr(self.songinfo, 'artist', "")
			artist = artist.replace("/", "")
			album = getattr(self.songinfo, 'album', "")
			album = album.replace("/", "")
			try:
				filename = os.path.expanduser("~/.covers/" + artist + "-" + album + ".jpg")
				if filename == self.lastalbumart:
					# No need to update..
					self.stop_art_update = False
					return
				self.lastalbumart = None
				songdir = os.path.dirname(self.songinfo.file)
				if os.path.exists(filename):
					gobject.idle_add(self.set_image_for_cover, filename)
				else:
					if self.covers_pref == self.ART_LOCAL or self.covers_pref == self.ART_LOCAL_REMOTE:
						imgfound = self.check_for_local_images(songdir)
					else:
						imgfound = self.check_remote_images(artist, album, filename)
					if not imgfound:
						if self.covers_pref == self.ART_LOCAL_REMOTE:
							self.check_remote_images(artist, album, filename)
						elif self.covers_pref == self.ART_REMOTE_LOCAL:
							self.check_for_local_images(songdir)
			except:
				self.set_default_icon_for_art(True)
		else:
			self.set_default_icon_for_art(True)

	def check_for_local_images(self, songdir):
		if os.path.exists(self.musicdir + songdir + "/cover.jpg"):
			gobject.idle_add(self.set_image_for_cover, self.musicdir + songdir + "/cover.jpg")
			return True
		elif os.path.exists(self.musicdir + songdir + "/folder.jpg"):
			gobject.idle_add(self.set_image_for_cover, self.musicdir + songdir + "/folder.jpg")
			return True
		else:
			self.single_img_in_dir = self.get_single_img_in_path(songdir)
			if self.single_img_in_dir:
				gobject.idle_add(self.set_image_for_cover, self.musicdir + songdir + "/" + self.single_img_in_dir)
				return True
		return False

	def check_remote_images(self, artist, album, filename):
		self.set_default_icon_for_art(True)
		self.download_image_to_filename(artist, album, filename)
		if os.path.exists(filename):
			gobject.idle_add(self.set_image_for_cover, filename)
			return True
		return False

	def set_default_icon_for_art(self, set_lastalbumart_none=False):
		gobject.idle_add(self.albumimage.set_from_file, self.sonatacd)
		if self.infowindow_visible:
			gobject.idle_add(self.infowindow_image.set_from_file, self.sonatacd_large)
		gobject.idle_add(self.set_tooltip_art, gtk.gdk.pixbuf_new_from_file(self.sonatacd))
		if set_lastalbumart_none:
			self.lastalbumart = None

	def get_single_img_in_path(self, songdir):
		single_img = None
		if os.path.exists(self.musicdir + songdir):
			for file in os.listdir(self.musicdir + songdir):
				# Check against gtk+ supported image formats
				for i in gtk.gdk.pixbuf_get_formats():
					if os.path.splitext(file)[1].replace(".","").lower() in i['extensions']:
						if single_img == None:
							single_img = file
						else:
							return False
			return single_img
		else:
			return False

	def set_image_for_cover(self, filename):
		if self.filename_is_for_current_song(filename):
			if os.path.exists(filename):
				# We use try here because the file might exist, but still
				# be downloading so it's not complete
				try:
					pix = gtk.gdk.pixbuf_new_from_file(filename)
					(pix1, w, h) = self.get_pixbuf_of_size(pix, 75)
					pix1 = self.pixbuf_add_border(pix1)
					pix1 = self.pixbuf_pad(pix1, 77, 77)
					if self.infowindow_visible:
						(pix2, w, h) = self.get_pixbuf_of_size(pix, 298)
						pix2 = self.pixbuf_add_border(pix2)
					self.albumimage.set_from_pixbuf(pix1)
					self.set_tooltip_art(pix1)
					if self.infowindow_visible:
						self.infowindow_image.set_from_pixbuf(pix2)
					self.lastalbumart = filename
					del pix
					del pix1
					del pix2
				except:
					pass
				self.call_gc_collect = True

	def filename_is_for_current_song(self, filename):
		# Since there can be multiple threads that are getting album art,
		# this will ensure that only the artwork for the currently playing
		# song is displayed
		if self.conn and self.status and self.status.state in ['play', 'pause']:
			artist = getattr(self.songinfo, 'artist', "")
			artist = artist.replace("/", "")
			album = getattr(self.songinfo, 'album', "")
			album = album.replace("/", "")
			currfilename = os.path.expanduser("~/.covers/" + artist + "-" + album + ".jpg")
			if filename == currfilename:
				return True
			songdir = os.path.dirname(self.songinfo.file)
			currfilename = self.musicdir + songdir + "/cover.jpg"
			if filename == currfilename:
				return True
			currfilename = self.musicdir + songdir + "/folder.jpg"
			if filename == currfilename:
				return True
			if self.single_img_in_dir:
				currfilename = self.musicdir + songdir + "/" + self.single_img_in_dir
				if filename == currfilename:
					return True
		# If we got this far, no match:
		return False

	def download_image_to_filename(self, artist, album, dest_filename, all_images=False, populate_imagelist=False):
		# Returns False if no images found
		imgfound = False
		if len(artist) == 0 and len(album) == 0:
			self.downloading_image = False
			return imgfound
		try:
			self.downloading_image = True
			artist = urllib.quote(artist)
			album = urllib.quote(album)
			amazon_key = "12DR2PGAQT303YTEWP02"
			search_url = "http://webservices.amazon.com/onca/xml?Service=AWSECommerceService&AWSAccessKeyId=" + amazon_key + "&Operation=ItemSearch&SearchIndex=Music&Artist=" + artist + "&ResponseGroup=Images&Keywords=" + album
			request = urllib2.Request(search_url)
			request.add_header('Accept-encoding', 'gzip')
			opener = urllib2.build_opener()
			f = opener.open(request).read()
			curr_pos = 200    # Skip header..
			# Check if any results were returned; if not, search
			# again with just the artist name:
			img_url = f[f.find("<URL>", curr_pos)+len("<URL>"):f.find("</URL>", curr_pos)]
			if len(img_url) == 0:
				search_url = "http://webservices.amazon.com/onca/xml?Service=AWSECommerceService&AWSAccessKeyId=" + amazon_key + "&Operation=ItemSearch&SearchIndex=Music&Artist=" + artist + "&ResponseGroup=Images"
				request = urllib2.Request(search_url)
				request.add_header('Accept-encoding', 'gzip')
				opener = urllib2.build_opener()
				f = opener.open(request).read()
				img_url = f[f.find("<URL>", curr_pos)+len("<URL>"):f.find("</URL>", curr_pos)]
				# And if that fails, try one last time with just the album name:
				if len(img_url) == 0:
					search_url = "http://webservices.amazon.com/onca/xml?Service=AWSECommerceService&AWSAccessKeyId=" + amazon_key + "&Operation=ItemSearch&SearchIndex=Music&ResponseGroup=Images&Keywords=" + album
					request = urllib2.Request(search_url)
					request.add_header('Accept-encoding', 'gzip')
					opener = urllib2.build_opener()
					f = opener.open(request).read()
					img_url = f[f.find("<URL>", curr_pos)+len("<URL>"):f.find("</URL>", curr_pos)]
			if all_images:
				curr_img = 1
				img_url = " "
				if len(img_url) == 0:
					self.downloading_image = False
					return imgfound
				while len(img_url) > 0 and curr_pos > 0:
					img_url = ""
					curr_pos = f.find("<LargeImage>", curr_pos+10)
					img_url = f[f.find("<URL>", curr_pos)+len("<URL>"):f.find("</URL>", curr_pos)]
					if len(img_url) > 0:
						if self.stop_art_update:
							self.downloading_image = False
							return imgfound
						dest_filename_curr = dest_filename.replace("<imagenum>", str(curr_img))
						urllib.urlretrieve(img_url, dest_filename_curr)
						if populate_imagelist:
							# This populates self.imagelist for the remote image window
							if os.path.exists(dest_filename_curr):
								pix = gtk.gdk.pixbuf_new_from_file(dest_filename_curr)
								pix = pix.scale_simple(148, 148, gtk.gdk.INTERP_HYPER)
								pix = self.pixbuf_add_border(pix)
								if self.stop_art_update:
									self.downloading_image = False
									return imgfound
								self.imagelist.append([curr_img, pix, ""])
								del pix
								self.remotefilelist.append(dest_filename_curr)
								imgfound = True
								if curr_img == 1:
									self.allow_art_search = True
							self.change_cursor(None)
						curr_img += 1
						# Skip the next LargeImage:
						curr_pos = f.find("<LargeImage>", curr_pos+10)
			else:
				curr_pos = f.find("<LargeImage>", curr_pos+10)
				img_url = f[f.find("<URL>", curr_pos)+len("<URL>"):f.find("</URL>", curr_pos)]
				if len(img_url) > 0:
					urllib.urlretrieve(img_url, dest_filename)
					imgfound = True
		except:
			pass
		self.downloading_image = False
		return imgfound
		

	def labelnotify(self, *args):
		if self.sonata_loaded:
			if self.conn and self.status and self.status.state in ['play', 'pause']:
				if self.show_covers:
					self.traytips.set_size_request(350, -1)
				else:
					self.traytips.set_size_request(250, -1)
			else:
				self.traytips.set_size_request(-1, -1)
			if self.show_notification:
				try:
					gobject.source_remove(self.traytips.notif_handler)
				except:
					pass
				if self.conn and self.status and self.status.state in ['play', 'pause']:
					try:
						self.traytips.use_notifications_location = True
						if HAVE_STATUS_ICON:
							self.traytips._real_display(self.statusicon)
						elif HAVE_EGG:
							self.traytips._real_display(self.trayeventbox)
						else:
							self.traytips._real_display(None)
						if self.popup_option != len(self.popuptimes)-1:
							timeout = int(self.popuptimes[self.popup_option])*1000
							self.traytips.notif_handler = gobject.timeout_add(timeout, self.traytips.hide)
						else:
							# -1 indicates that the timeout should be forever.
							# We don't want to pass None, because then Sonata
							# would think that there is no current notification
							self.traytips.notif_handler = -1
					except:
						pass
				else:
					self.traytips.hide()
			elif self.traytips.get_property('visible'):
				self.traytips._real_display(self.trayeventbox)

	def progressbarnotify_fraction(self, *args):
		self.trayprogressbar.set_fraction(self.progressbar.get_fraction())

	def progressbarnotify_text(self, *args):
		self.trayprogressbar.set_text(self.progressbar.get_text())

	def update_infofile(self):
 		if self.use_infofile is True:
 			try:
 				info_file = open(self.infofile_path, 'w')

 				if self.status.state in ['play']:
 					info_file.write('Status: ' + 'Playing' + '\n')
 				elif self.status.state in ['pause']:
 					info_file.write('Status: ' + 'Paused' + '\n')
				elif self.status.state in ['stop']:
 					info_file.write('Status: ' + 'Stopped' + '\n')
 				try:
 					info_file.write('Title: ' + self.songinfo.artist + ' - ' + self.songinfo.title + '\n')
 				except:
 					try:
 	 					info_file.write('Title: ' + self.songinfo.title + '\n') # No Arist in streams
 					except:
 						info_file.write('Title: No - ID Tag\n')
				info_file.write('Album: ' + getattr(self.songinfo, 'album', 'No Data') + '\n')
				info_file.write('Track: ' + getattr(self.songinfo, 'track', '0') + '\n')
 				info_file.write('File: ' + getattr(self.songinfo, 'file', 'No Data') + '\n')
				info_file.write('Time: ' + getattr(self.songinfo, 'time', '0') + '\n')
 				info_file.write('Volume: ' + self.status.volume + '\n')
 				info_file.write('Repeat: ' + self.status.repeat + '\n')
 				info_file.write('Shuffle: ' + self.status.random + '\n')
 				info_file.close()
 			except:
 				pass

	#################
	# Gui Callbacks #
	#################

	def on_delete_event_yes(self, widget):
		self.exit_now = True
		self.on_delete_event(None, None)

	# This one makes sure the program exits when the window is closed
	def on_delete_event(self, widget, data=None):
		if not self.exit_now and self.minimize_to_systray:
			if HAVE_STATUS_ICON and self.statusicon.is_embedded() and self.statusicon.get_visible():
				self.withdraw_app()
				return True
			elif HAVE_EGG and self.trayicon.get_property('visible') == True:
				self.withdraw_app()
				return True
		self.settings_save()
		if self.conn and self.stop_on_exit:
			self.stop(None)
		sys.exit()
		return False

	def on_window_state_change(self, widget, event):
		self.volume_hide()

	def on_window_lost_focus(self, widget, event):
		self.volume_hide()

	def on_window_configure(self, widget, event):
		width, height = self.window.get_size()
		if self.expanded: self.w, self.h = width, height
		else: self.w = width
		self.x, self.y = self.window.get_position()
		# The follow line cases the volume window to never
		# disappear when the button's clicked. Why was it
		# added?
		#self.volume_hide()

	def on_infowindow_configure(self, widget, event, titlelabel, labels_right):
		self.infowindow_w, self.infowindow_h = self.infowindow.get_size()
		self.infowindow_x, self.infowindow_y = self.infowindow.get_position()
		labelwidth = self.infowindow.allocation.width - titlelabel.get_size_request()[0] - 50
		for label in labels_right:
			label.set_size_request(labelwidth, -1)

	def expand(self, action):
		if not self.expander.get_expanded():
			self.expander.set_expanded(False)
			self.on_expander_activate(None)
			self.expander.set_expanded(True)

	def collapse(self, action):
		if self.expander.get_expanded():
			self.expander.set_expanded(True)
			self.on_expander_activate(None)
			self.expander.set_expanded(False)

	def on_expander_activate(self, expander):
		currheight = self.window.get_size()[1]
		self.expanded = False
		# Note that get_expanded() will return the state of the expander
		# before this current click
		window_about_to_be_expanded = not self.expander.get_expanded()
		if window_about_to_be_expanded:
			if self.show_statusbar:
				self.statusbar.show()
			self.notebook.show_all()
		else:
			self.statusbar.hide()
			self.notebook.hide()
		if not (self.conn and self.status and self.status.state in ['play', 'pause']):
			if window_about_to_be_expanded:
				self.cursonglabel.set_markup('<big><b>' + _('Stopped') + '</b></big>\n<small>' + _('Click to collapse') + '</small>')
			else:
				self.cursonglabel.set_markup('<big><b>' + _('Stopped') + '</b></big>\n<small>' + _('Click to expand') + '</small>')
		# Now we wait for the height of the player to increase, so that
		# we know the list is visible. This is pretty hacky, but works.
		if self.window_owner:
			if window_about_to_be_expanded:
				while self.window.get_size()[1] == currheight:
					gtk.main_iteration()
				# Notebook is visible, now resize:
				self.window.resize(self.w, self.h)
			else:
				self.window.resize(self.w, 1)
		if window_about_to_be_expanded:
			self.expanded = True
			self.tooltips.set_tip(self.expander, _("Click to collapse the player"))
			if self.status and self.status.state in ['play','pause']:
				gobject.idle_add(self.keep_song_visible_in_list)
		else:
			self.tooltips.set_tip(self.expander, _("Click to expand the player"))
		# Put focus to the notebook:
		self.on_notebook_page_change(None, None, self.notebook.get_current_page())
		return

	# This callback allows the user to seek to a specific portion of the song
	def on_progressbar_button_press_event(self, widget, event):
		if event.button == 1:
			if self.status and self.status.state in ['play', 'pause']:
				at, length = [int(c) for c in self.status.time.split(':')]
				try:
					progressbarsize = self.progressbar.allocation
					seektime = int((event.x/progressbarsize.width) * length)
					self.seek(int(self.status.song), seektime)
				except:
					pass
			return True

	def on_progressbar_scroll_event(self, widget, event):
		if self.status and self.status.state in ['play', 'pause']:
			try:
				gobject.source_remove(self.seekidle)
			except:
				pass
			self.seekidle = gobject.idle_add(self.seek_when_idle, event.direction)
		return True

	def seek_when_idle(self, direction):
		at, length = [int(c) for c in self.status.time.split(':')]
		try:
			if direction == gtk.gdk.SCROLL_UP:
				seektime = int(self.status.time.split(":")[0]) - 5
				if seektime < 0: seektime = 0
			elif direction == gtk.gdk.SCROLL_DOWN:
				seektime = int(self.status.time.split(":")[0]) + 5
				if seektime > self.songinfo.time:
					seektime = self.songinfo.time
			self.seek(int(self.status.song), seektime)
		except:
			pass

	def on_sort_by_artist(self, action):
		self.sort('artist')

	def on_sort_by_album(self, action):
		self.sort('album')

	def on_sort_by_title(self, action):
		self.sort('title')

	def on_sort_by_file(self, action):
		self.sort('file')

	def sort(self, type):
		if self.conn:
			self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
			while gtk.events_pending():
				gtk.main_iteration()
			list = []
			for track in self.songs:
				dict = {}
				# Those items that don't have the specified tag will be put at
				# the end of the list (hence the 'zzzzzzz'):
				dict["sortby"] = getattr(track, type, 'zzzzzzzz')
				if type == 'file':
					dict["sortby"] = dict["sortby"].split('/')[-1]
				dict["id"] = track.id
				list.append(dict)
			list.sort(key=lambda x: x["sortby"].lower()) # Remove case sensitivity
			# Now that we have the order, move the songs as appropriate:
			pos = 0
			self.conn.send.command_list_begin()
			for item in list:
				self.conn.send.moveid(int(item["id"]), pos)
				pos = pos + 1
			self.conn.do.command_list_end()

	def on_sort_reverse(self, action):
		if self.conn:
			self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
			while gtk.events_pending():
				gtk.main_iteration()
			top = 0
			bot = len(self.songs)-1
			self.conn.send.command_list_begin()
			while top < bot:
				self.conn.send.swap(top, bot)
				top = top + 1
				bot = bot - 1
			self.conn.do.command_list_end()

	def on_sort_random(self, action):
		if self.conn:
			self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
			while gtk.events_pending():
				gtk.main_iteration()
			self.conn.do.shuffle()

	def on_drag_drop(self, treeview, drag_context, x, y, selection, info, timestamp):
		model = treeview.get_model()
		foobar, selected = self.current_selection.get_selected_rows()
		drop_info = treeview.get_dest_row_at_pos(x, y)
		
		# calculate all this now before we start moving stuff
		drag_sources = []
		for path in selected:
			index = path[0]
			iter = model.get_iter(path)
			id = model.get_value(iter, 0)
			text = model.get_value(iter, 1)
			drag_sources.append([index, iter, id, text])

		# We will manipulate self.songs and model to prevent the entire playlist
		# from refreshing
		offset = 0
		top_row_for_selection = len(model)
		self.conn.send.command_list_begin()
		for source in drag_sources:
			index, iter, id, text = source
			if drop_info:
				destpath, position = drop_info
				dest = destpath[0] + offset
				if dest < index:
					offset = offset + 1
				if position in (gtk.TREE_VIEW_DROP_BEFORE, gtk.TREE_VIEW_DROP_INTO_OR_BEFORE):
					self.songs.insert(dest, self.songs[index])
					if dest < index+1:
						self.songs.pop(index+1)
						self.conn.send.moveid(id, dest)
					else:
						self.songs.pop(index)
						self.conn.send.moveid(id, dest-1)
					model.insert(dest, model[index])
					treeview.get_selection().select_path(dest)
					model.remove(iter)
				else:
					self.songs.insert(dest+1, self.songs[index])
					if dest < index:
						self.songs.pop(index+1)
						self.conn.send.moveid(id, dest+1)
					else:
						self.songs.pop(index)
						self.conn.send.moveid(id, dest)
					model.insert(dest+1, model[index])
					treeview.get_selection().select_path(dest+1)
					model.remove(iter)
			else:
				dest = len(self.songs) - 1
				self.conn.send.moveid(id, dest)
				self.songs.insert(dest+1, self.songs[index])
				self.songs.pop(index)
				model.insert(dest+1, model[index])
				treeview.get_selection().select_path(dest+1)
				model.remove(iter)
			# now fixup
			for source in drag_sources:
				if dest < index:
					# we moved it back, so all indexes inbetween increased by 1
					if dest < source[0] < index:
						source[0] += 1
				else:
					# we moved it ahead, so all indexes inbetween decreased by 1
					if index < source[0] < dest:
						source[0] -= 1
		self.conn.do.command_list_end()

		if drag_context.action == gtk.gdk.ACTION_MOVE:
			drag_context.finish(True, True, timestamp)
		self.iterate_now()

	def on_current_button_press(self, widget, event):
		self.volume_hide()
		if event.button == 3:
			self.set_menu_contextual_items_visible()
			self.mainmenu.popup(None, None, None, event.button, event.time)
			# Don't change the selection for a right-click. This
			# will allow the user to select multiple rows and then
			# right-click (instead of right-clicking and having
			# the current selection change to the current row)
			if self.current_selection.count_selected_rows() > 1:
				return True

	def on_current_button_released(self, widget, event):
		return

	def on_current_popup_menu(self, widget):
		self.mainmenu.popup(None, None, None, 3, 0)

	def updatedb(self, widget):
		if self.conn:
			self.conn.do.update('/')
			self.iterate_now()

	def updatedb_path(self, action):
		if self.conn:
			if self.notebook.get_current_page() == self.TAB_LIBRARY:
				model, selected = self.browser_selection.get_selected_rows()
				iters = [model.get_iter(path) for path in selected]
				if len(iters) > 0:
					# If there are selected rows, update these paths..
					for iter in iters:
						self.conn.do.update(self.browserdata.get_value(iter, 1))
				else:
					# If no selection, update the current path...
					self.conn.do.update(self.browser.wd)
				self.iterate_now()

	def on_image_activate(self, widget, event):
		if widget == self.imageeventbox:
			self.remote_from_infowindow = False
		else:
			self.remote_from_infowindow = True
		self.window.handler_block(self.mainwinhandler)
		if event.button == 1:
			self.volume_hide()
			self.on_infowindow_show()
		elif event.button == 3:
			if self.conn and self.status and self.status.state in ['play', 'pause']:
				self.UIManager.get_widget('/imagemenu/chooseimage_menu/').hide()
				self.UIManager.get_widget('/imagemenu/localimage_menu/').hide()
				if self.covers_pref != self.ART_LOCAL:
					self.UIManager.get_widget('/imagemenu/chooseimage_menu/').show()
				if self.covers_pref != self.ART_REMOTE:
					self.UIManager.get_widget('/imagemenu/localimage_menu/').show()
				artist = getattr(self.songinfo, 'artist', None)
				album = getattr(self.songinfo, 'album', None)
				if artist or album:
					self.imagemenu.popup(None, None, None, event.button, event.time)
		gobject.timeout_add(50, self.unblock_window_popup_handler)
		return False

	def on_image_motion_cb(self, widget, context, x, y, time):
		context.drag_status(gtk.gdk.ACTION_COPY, time)
		return True

	def on_image_drop_cb(self, widget, context, x, y, selection, info, time):
		if self.conn and self.status and self.status.state in ['play', 'pause']:
			uri = selection.data.strip()
			path = urllib.url2pathname(uri)
			paths = path.rsplit('\n')
			for i, path in enumerate(paths):
				paths[i] = path.rstrip('\r')
				# Clean up (remove preceding "file://" or "file:")
				if paths[i].startswith('file://'):
					paths[i] = paths[i][7:]
				elif paths[i].startswith('file:'):
					paths[i] = paths[i][5:]
				paths[i] = os.path.abspath(paths[i])
				if self.valid_image(paths[i]):
					artist = getattr(self.songinfo, 'artist', "")
					artist = artist.replace("/", "")
					album = getattr(self.songinfo, 'album', "")
					album = album.replace("/", "")
					dest_filename = os.path.expanduser("~/.covers/" + artist + "-" + album + ".jpg")
					shutil.copyfile(paths[i], dest_filename)
					self.lastalbumart = None
					self.update_album_art()

	def valid_image(self, file):
		test = gtk.gdk.pixbuf_get_file_info(file)
		if test == None:
			return False
		else:
			return True

	def on_infowindow_show(self, action=None):
		if self.infowindow_visible:
			self.infowindow.present()
			return
		self.infowindow = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.infowindow.set_title(_('Song Info'))
		self.infowindow.set_size_request(380, -1)
		self.infowindow.set_default_size(self.infowindow_w, self.infowindow_h)
		self.infowindow.move(self.infowindow_x, self.infowindow_y)
		icon = self.infowindow.render_icon('sonata', gtk.ICON_SIZE_DIALOG)
		self.infowindow.set_icon(icon)
		self.infowindow_notebook = gtk.Notebook()
		self.infowindow_notebook.set_tab_pos(gtk.POS_TOP)
		self.infowindow_notebook.set_size_request(350, 350)
		titlehbox = gtk.HBox()
		titlelabel = gtk.Label()
		titlelabel.set_markup("<b>  " + _("Title") + ":</b>")
		self.infowindow_titlelabel = gtk.Label("")
		titlehbox.pack_start(titlelabel, False, False, 2)
		titlehbox.pack_start(self.infowindow_titlelabel, False, False, 2)
		artisthbox = gtk.HBox()
		artistlabel = gtk.Label()
		artistlabel.set_markup("<b>  " + _("Artist") + ":</b>")
		self.infowindow_artistlabel = gtk.Label("")
		artisthbox.pack_start(artistlabel, False, False, 2)
		artisthbox.pack_start(self.infowindow_artistlabel, False, False, 2)
		albumhbox = gtk.HBox()
		albumlabel = gtk.Label()
		albumlabel.set_markup("<b>  " + _("Album") + ":</b>")
		self.infowindow_albumlabel = gtk.Label("")
		albumhbox.pack_start(albumlabel, False, False, 2)
		albumhbox.pack_start(self.infowindow_albumlabel, False, False, 2)
		datehbox = gtk.HBox()
		datelabel = gtk.Label()
		datelabel.set_markup("<b>  " + _("Date") + ":</b>")
		self.infowindow_datelabel = gtk.Label("")
		datehbox.pack_start(datelabel, False, False, 2)
		datehbox.pack_start(self.infowindow_datelabel, False, False, 2)
		trackhbox = gtk.HBox()
		tracklabel = gtk.Label()
		tracklabel.set_markup("<b>  " + _("Track") + ":</b>")
		self.infowindow_tracklabel = gtk.Label("")
		trackhbox.pack_start(tracklabel, False, False, 2)
		trackhbox.pack_start(self.infowindow_tracklabel, False, False, 2)
		genrehbox = gtk.HBox()
		genrelabel = gtk.Label()
		genrelabel.set_markup("<b>  " + _("Genre") + ":</b>")
		self.infowindow_genrelabel = gtk.Label("")
		genrehbox.pack_start(genrelabel, False, False, 2)
		genrehbox.pack_start(self.infowindow_genrelabel, False, False, 2)
		pathhbox = gtk.HBox()
		pathlabel = gtk.Label()
		pathlabel.set_markup("<b>  " + _("Path") + ":</b>")
		self.infowindow_pathlabel = gtk.Label("")
		pathhbox.pack_start(pathlabel, False, False, 2)
		pathhbox.pack_start(self.infowindow_pathlabel, False, False, 2)
		filehbox = gtk.HBox()
		filelabel = gtk.Label()
		filelabel.set_markup("<b>  " + _("File") + ":</b>")
		self.infowindow_filelabel = gtk.Label("")
		filehbox.pack_start(filelabel, False, False, 2)
		filehbox.pack_start(self.infowindow_filelabel, False, False, 2)
		timehbox = gtk.HBox()
		timelabel = gtk.Label()
		timelabel.set_markup("<b>  " + _("Time") + ":</b>")
		self.infowindow_timelabel = gtk.Label("")
		timehbox.pack_start(timelabel, False, False, 2)
		timehbox.pack_start(self.infowindow_timelabel, False, False, 2)
		bitratehbox = gtk.HBox()
		bitratelabel = gtk.Label()
		bitratelabel.set_markup("<b>  " + _("Bitrate") + ":</b>")
		self.infowindow_bitratelabel = gtk.Label("")
		bitratehbox.pack_start(bitratelabel, False, False, 2)
		bitratehbox.pack_start(self.infowindow_bitratelabel, False, False, 2)
		labels_left = [titlelabel, artistlabel, albumlabel, datelabel, tracklabel, genrelabel, pathlabel, filelabel, timelabel, bitratelabel]
		self.set_label_widths_equal(labels_left)
		for label in labels_left:
			label.set_alignment(1, 0)
		labels_right = [self.infowindow_titlelabel, self.infowindow_artistlabel, self.infowindow_albumlabel, self.infowindow_datelabel, self.infowindow_tracklabel, self.infowindow_genrelabel, self.infowindow_pathlabel, self.infowindow_filelabel, self.infowindow_timelabel, self.infowindow_bitratelabel]
		labelwidth = self.infowindow.get_size_request()[0] - titlelabel.get_size_request()[0] - 80
		for label in labels_right:
			label.set_alignment(0, 0)
			label.set_line_wrap(True)
			label.set_selectable(True)
		hboxes = [titlehbox, artisthbox, albumhbox, datehbox, trackhbox, genrehbox, pathhbox, filehbox, timehbox, bitratehbox]
		vbox = gtk.VBox()
		vbox.pack_start(gtk.Label(), False, False, 0)
		nblabel1 = gtk.Label()
		nblabel1.set_text_with_mnemonic(_("_Song Info"))
		for hbox in hboxes:
			vbox.pack_start(hbox, False, False, 3)
		if HAVE_TAGPY:
			# Add Edit button:
			self.edittag_button = gtk.Button(' ' + _("_Edit..."))
			self.edittag_button.set_image(gtk.image_new_from_stock(gtk.STOCK_EDIT, gtk.ICON_SIZE_MENU))
			self.edittag_button.connect('clicked', self.on_edittag_click)
			hbox_edittag = gtk.HBox()
			hbox_edittag.pack_start(self.edittag_button, False, False, 10)
			hbox_edittag.pack_start(gtk.Label(), True, True, 0)
			vbox.pack_start(gtk.Label(), True, True, 0)
			vbox.pack_start(hbox_edittag, False, False, 6)
		self.infowindow_notebook.append_page(vbox, nblabel1)
		# Add cover art:
		nblabel2 = gtk.Label()
		nblabel2.set_text_with_mnemonic(_("_Cover Art"))
		eventbox = gtk.EventBox()
		eventbox.drag_dest_set(gtk.DEST_DEFAULT_HIGHLIGHT | gtk.DEST_DEFAULT_DROP, [("text/uri-list", 0, 80)], gtk.gdk.ACTION_DEFAULT)
		self.infowindow_image = gtk.Image()
		self.infowindow_image.set_alignment(0.5, 0.5)
		eventbox.connect('button_press_event', self.on_image_activate)
		eventbox.connect('drag_motion', self.on_image_motion_cb)
		eventbox.connect('drag_data_received', self.on_image_drop_cb)
		eventbox.add(self.infowindow_image)
		self.infowindow_notebook.append_page(eventbox, nblabel2)
		gobject.idle_add(self.infowindow_image.set_from_file, self.sonatacd_large)
		# Add album info:
		nblabel3 = gtk.Label()
		nblabel3.set_text_with_mnemonic(_("_Album Info"))
		albumScrollWindow = gtk.ScrolledWindow()
		albumScrollWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
		self.albuminfoBuffer = gtk.TextBuffer()
		albuminfoView = gtk.TextView(self.albuminfoBuffer)
		albuminfoView.set_editable(False)
		albumScrollWindow.add_with_viewport(albuminfoView)
		self.infowindow_notebook.append_page(albumScrollWindow, nblabel3)
		self.infowindow_add_lyrics_tab()
		hbox_main = gtk.HBox()
		hbox_main.pack_start(self.infowindow_notebook, True, True, 15)
		vbox_inner = gtk.VBox()
		vbox_inner.pack_start(hbox_main, True, True, 10)
		hbox_close = gtk.HBox()
		hbox_close.pack_start(gtk.Label(), True, True, 0)
		closebutton = gtk.Button(gtk.STOCK_CLOSE, gtk.STOCK_CLOSE)
		closebutton.connect('clicked', self.on_infowindow_hide)
		hbox_close.pack_start(closebutton, False, False, 15)
		vbox_inner.pack_start(hbox_close, False, False, 0)
		vbox_main = gtk.VBox()
		vbox_main.pack_start(vbox_inner, True, True, 5)
		self.infowindow.add(vbox_main)
		self.lastalbumart = ""
		self.update_album_art()
		self.infowindow.show_all()
		self.infowindow_visible = True
		self.infowindow.connect('delete_event', self.on_infowindow_hide)
		self.infowindow.connect('key_press_event', self.on_infowindow_keypress)
		self.infowindow.connect('configure_event', self.on_infowindow_configure, titlelabel, labels_right)
		if self.infowindow_visible:
			self.infowindow_update(True, update_all=True)

	def infowindow_add_lyrics_tab(self, show_tab=False):
		if HAVE_WSDL and self.show_lyrics:
			nblabel4 = gtk.Label()
			nblabel4.set_text_with_mnemonic(_("_Lyrics"))
			scrollWindow = gtk.ScrolledWindow()
			scrollWindow.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
			self.lyricsBuffer = gtk.TextBuffer()
			lyricsView = gtk.TextView(self.lyricsBuffer)
			lyricsView.set_editable(False)
			lyricsView.set_wrap_mode(gtk.WRAP_WORD)
			scrollWindow.add_with_viewport(lyricsView)
			self.infowindow_notebook.append_page(scrollWindow, nblabel4)
			if show_tab:
				self.infowindow.show_all()

	def infowindow_remove_lyrics_tab(self):
		self.infowindow_notebook.remove_page(-1)

	def on_infowindow_hide(self, window, data=None):
		self.infowindow_visible = False
		self.infowindow.destroy()
	
	def on_infowindow_keypress(self, widget, event):
		shortcut = gtk.accelerator_name(event.keyval, event.state)
		shortcut = shortcut.replace("<Mod2>", "")
		if shortcut == '<Control>w' or shortcut == '<Control>q':
			self.on_infowindow_hide(widget)

	def infowindow_update(self, show_after_update=False, update_all=False):
		# update_all = True means that every tag should update. This is
		# only the case on song and status changes. Otherwise we only
		# want to update the minimum number of widgets so the user can
		# do things like select label text.
		if self.infowindow_visible:
			if self.conn:
				if self.status and self.status.state in ['play', 'pause']:
					if HAVE_TAGPY:
						self.edittag_button.set_sensitive(True)
					at, length = [int(c) for c in self.status.time.split(':')]
					at_time = convert_time(at)
					try:
						time = convert_time(int(self.songinfo.time))
						self.infowindow_timelabel.set_text(at_time + " / " + time)
					except:
						self.infowindow_timelabel.set_text(at_time)
					try:
						self.infowindow_bitratelabel.set_text(self.status.bitrate + " kbps")
					except:
						self.infowindow_bitratelabel.set_text('')
					if update_all:
						self.infowindow_titlelabel.set_text(getattr(self.songinfo, 'title', ''))
						self.infowindow_artistlabel.set_text(getattr(self.songinfo, 'artist', ''))
						self.infowindow_albumlabel.set_text(getattr(self.songinfo, 'album', ''))
						self.infowindow_datelabel.set_text(getattr(self.songinfo, 'date', ''))
						self.infowindow_genrelabel.set_text(getattr(self.songinfo, 'genre', ''))
						try:
							self.infowindow_tracklabel.set_text(str(int(self.songinfo.track.split('/')[0])))
						except:
							self.infowindow_tracklabel.set_text('')
						if os.path.exists(self.musicdir + os.path.dirname(self.songinfo.file)):
							self.infowindow_pathlabel.set_text(self.musicdir + os.path.dirname(self.songinfo.file))
						else:
							self.infowindow_pathlabel.set_text("/" + os.path.dirname(self.songinfo.file))
						self.infowindow_filelabel.set_text(os.path.basename(self.songinfo.file))
						if self.songinfo.has_key('album'):
							# Update album info:
							artist = []
							year = []
							albumtime = 0
							trackinfo = ""
							albuminfo = self.songinfo.album + "\n"
							for track in self.browse_search_album(self.songinfo.album):
								if track.has_key('title'):
									trackinfo = trackinfo + getattr(track, 'track', '0').split('/')[0].zfill(2) + ' - ' + track.title + '\n'
								else:
									trackinfo = trackinfo + getattr(track, 'track', '0').split('/')[0].zfill(2) + ' - ' + track.file.split('/')[-1] + '\n'
								if track.has_key('artist'):
									artist.append(track.artist)
								if track.has_key('date'):
									year.append(track.date)
								try:
									albumtime = albumtime + int(track.time)
								except:
									pass
							(artist, i) = remove_list_duplicates(artist, [], False)
							(year, i) = remove_list_duplicates(year, [], False)
							if len(artist) == 1:
								albuminfo = albuminfo + artist[0] + "\n"
							elif len(artist) > 0:
								albuminfo = albuminfo + _("Various Artists") + "\n"
							if len(year) == 1:
								albuminfo = albuminfo + year[0] + "\n"
							albuminfo = albuminfo + convert_time(albumtime) + "\n"
							albuminfo = albuminfo + "\n\n" + trackinfo
							if albuminfo != self.albuminfoBuffer.get_text(self.albuminfoBuffer.get_start_iter(), self.albuminfoBuffer.get_end_iter()):
								self.albuminfoBuffer.set_text(albuminfo)
						else:
							self.albuminfoBuffer.set_text(_("Album name not set."))
						# Update lyrics:
						if HAVE_WSDL and self.show_lyrics:
							if self.songinfo.has_key('artist') and self.songinfo.has_key('title'):
								try:
									lyricThread = threading.Thread(target=self.infowindow_get_lyrics, args=(self.songinfo.artist, self.songinfo.title))
									lyricThread.setDaemon(True)
									lyricThread.start()
								except:
									self.infowindow_show_lyrics("")
							else:
								self.infowindow_show_lyrics(_("Artist or song title not set."))
					if show_after_update and self.infowindow_visible:
						gobject.idle_add(self.infowindow_show_now)
				else:
					if HAVE_TAGPY:
						self.edittag_button.set_sensitive(False)
					self.infowindow_timelabel.set_text("")
					self.infowindow_titlelabel.set_text("")
					self.infowindow_artistlabel.set_text("")
					self.infowindow_albumlabel.set_text("")
					self.infowindow_datelabel.set_text("")
					self.infowindow_tracklabel.set_text("")
					self.infowindow_genrelabel.set_text("")
					self.infowindow_pathlabel.set_text("")
					self.infowindow_filelabel.set_text("")
					self.infowindow_bitratelabel.set_text("")
					if HAVE_WSDL and self.show_lyrics:
						self.infowindow_show_lyrics("")
					self.albuminfoBuffer.set_text("")

	def infowindow_show_now(self):
		self.infowindow.show_all()
		self.infowindow_visible = True

	def infowindow_get_lyrics(self, artist, title):
		filename = os.path.expanduser('~/.lyrics/' + artist + '-' + title + '.txt')
		if os.path.exists(filename):
			# Re-use lyrics from file, if it exists:
			f = open(filename, 'r')
			lyrics = f.read()
			f.close()
			gobject.idle_add(self.infowindow_show_lyrics, lyrics, artist, title)
		else:
			# Fetch lyrics from lyricwiki.org
			gobject.idle_add(self.infowindow_show_lyrics, _("Fetching lyrics..."))
			if self.lyricServer is None:
				wsdlFile = "http://lyricwiki.org/server.php?wsdl"
				try:
					self.lyricServer = True
					timeout = socket.getdefaulttimeout()
					socket.setdefaulttimeout(self.LYRIC_TIMEOUT)
					self.lyricServer = WSDL.Proxy(wsdlFile)
				except:
					socket.setdefaulttimeout(timeout)
					lyrics = _("Couldn't connect to LyricWiki")
					gobject.idle_add(self.infowindow_show_lyrics, lyrics)
					self.lyricServer = None
					return
			try:
				timeout = socket.getdefaulttimeout()
				socket.setdefaulttimeout(self.LYRIC_TIMEOUT)
				lyrics = self.lyricServer.getSong(artist, title)["lyrics"]
				if lyrics.lower() != "not found":
					lyrics = artist + " - " + title + "\n\n" + lyrics
					gobject.idle_add(self.infowindow_show_lyrics, lyrics, artist, title)
					# Save lyrics to file:
					f = open(filename, 'w')
					f.write(lyrics)
					f.close()
				else:
					lyrics = _("Lyrics not found")
					gobject.idle_add(self.infowindow_show_lyrics, lyrics)
			except:
				lyrics = _("Fetching lyrics failed")
				gobject.idle_add(self.infowindow_show_lyrics, lyrics)
			socket.setdefaulttimeout(timeout)

	def infowindow_show_lyrics(self, lyrics, artist=None, title=None):
		if self.infowindow_visible:
			if artist is None and title is None:
				self.lyricsBuffer.set_text(lyrics)
			elif self.status and self.status.state in ['play', 'pause']:
				# Verify that we are displaying the correct lyrics:
				if self.songinfo.artist == artist and self.songinfo.title == title:
					self.lyricsBuffer.set_text(lyrics)

	def get_pixbuf_of_size(self, pixbuf, size):
		# Creates a pixbuf that fits in the specified square of sizexsize
		# while preserving the aspect ratio
		# Returns tuple: (scaled_pixbuf, actual_width, actual_height)
		image_width = pixbuf.get_width()
		image_height = pixbuf.get_height()
		if image_width-size > image_height-size:
			if image_width > size:
				image_height = int(size/float(image_width)*image_height)
				image_width = size
		else:
			if image_height > size:
				image_width = int(size/float(image_height)*image_width)
				image_height = size
		crop_pixbuf = pixbuf.scale_simple(image_width, image_height, gtk.gdk.INTERP_HYPER)
		return (crop_pixbuf, image_width, image_height)

	def pixbuf_add_border(self, pix):
		# Add a gray outline to pix. This will increase the pixbuf size by
		# 2 pixels lengthwise and heightwise, 1 on each side. Returns pixbuf.
		width = pix.get_width()
		height = pix.get_height()
		newpix = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, width+2, height+2)
		newpix.fill(0x858585ff)
		pix.copy_area(0, 0, width, height, newpix, 1, 1)
		return newpix

	def pixbuf_pad(self, pix, w, h):
		# Adds transparent canvas so that the pixbuf is of size (w,h). Also
		# centers the pixbuf in the canvas.
		width = pix.get_width()
		height = pix.get_height()
		transpbox = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, w, h)
		transpbox.fill(0xffff00)
		x_pos = int((w - width)/2)
		y_pos = int((h - height)/2)
		pix.copy_area(0, 0, width, height, transpbox, x_pos, y_pos)
		return transpbox

	def unblock_window_popup_handler(self):
		self.window.handler_unblock(self.mainwinhandler)

	def change_cursor(self, type):
		for i in gtk.gdk.window_get_toplevels():
			i.set_cursor(type)

	def update_preview(self, file_chooser, preview):
		filename = file_chooser.get_preview_filename()
		pixbuf = None
		try:
			pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(filename, 128, 128)
		except:
			pass
		if pixbuf == None:
			try:
				pixbuf = gtk.gdk.PixbufAnimation(filename).get_static_image()
				width = pixbuf.get_width()
				height = pixbuf.get_height()
				if width > height:
					pixbuf = pixbuf.scale_simple(128, int(float(height)/width*128), gtk.gdk.INTERP_HYPER)
				else:
					pixbuf = pixbuf.scale_simple(int(float(width)/height*128), 128, gtk.gdk.INTERP_HYPER)
			except:
				pass
		if pixbuf == None:
			pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, 1, 8, 128, 128)
			pixbuf.fill(0x00000000)
		preview.set_from_pixbuf(pixbuf)
		have_preview = True
		file_chooser.set_preview_widget_active(have_preview)
		del pixbuf
		self.call_gc_collect = True

	def on_choose_image_local(self, widget):
		dialog = gtk.FileChooserDialog(title=_("Open Image"),action=gtk.FILE_CHOOSER_ACTION_OPEN,buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_OPEN,gtk.RESPONSE_OK))
		filter = gtk.FileFilter()
		filter.set_name(_("Images"))
		filter.add_pixbuf_formats()
		dialog.add_filter(filter)
		filter = gtk.FileFilter()
		filter.set_name(_("All files"))
		filter.add_pattern("*")
		dialog.add_filter(filter)
		preview = gtk.Image()
		dialog.set_preview_widget(preview)
		dialog.set_use_preview_label(False)
		dialog.connect("update-preview", self.update_preview, preview)
		dialog.connect("response", self.choose_image_local_response)
		dialog.set_default_response(gtk.RESPONSE_OK)
		songdir = os.path.dirname(self.songinfo.file)
		currdir = self.musicdir + songdir
		if os.path.exists(currdir):
			dialog.set_current_folder(currdir)
		self.local_artist = getattr(self.songinfo, 'artist', "")
		self.local_artist = self.local_artist.replace("/", "")
		self.local_album = getattr(self.songinfo, 'album', "")
		self.local_album = self.local_album.replace("/", "")
		dialog.show()

	def choose_image_local_response(self, dialog, response):
		if response == gtk.RESPONSE_OK:
			filename = dialog.get_filenames()[0]
			dest_filename = os.path.expanduser("~/.covers/" + self.local_artist + "-" + self.local_album + ".jpg")
			# Remove file if already set:
			if os.path.exists(dest_filename):
				os.remove(dest_filename)
			# Copy file to covers dir:
			shutil.copyfile(filename, dest_filename)
			# And finally, set the image in the interface:
			self.lastalbumart = None
			self.update_album_art()
		dialog.destroy()

	def on_choose_image(self, widget):
		if self.remote_from_infowindow:
			choose_dialog = gtk.Dialog(_("Choose Cover Art"), self.infowindow, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
		else:
			choose_dialog = gtk.Dialog(_("Choose Cover Art"), self.window, gtk.DIALOG_MODAL, (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
		choosebutton = choose_dialog.add_button(_("Choose"), gtk.RESPONSE_ACCEPT)
		chooseimage = gtk.Image()
		chooseimage.set_from_stock(gtk.STOCK_CONVERT, gtk.ICON_SIZE_BUTTON)
		choosebutton.set_image(chooseimage)
		choose_dialog.set_has_separator(False)
		choose_dialog.set_default(choosebutton)
		choose_dialog.set_resizable(False)
		scroll = gtk.ScrolledWindow()
		scroll.set_size_request(350, 325)
		scroll.set_policy(gtk.POLICY_NEVER, gtk.POLICY_ALWAYS)
		self.imagelist = gtk.ListStore(int, gtk.gdk.Pixbuf, str)
		imagewidget = gtk.IconView(self.imagelist)
		imagewidget.set_pixbuf_column(1)
		imagewidget.set_text_column(2)
		imagewidget.set_columns(2)
		imagewidget.set_item_width(150)
		imagewidget.set_spacing(5)
		imagewidget.set_margin(10)
		imagewidget.set_selection_mode(gtk.SELECTION_SINGLE)
		imagewidget.select_path("0")
		imagewidget.connect('item-activated', self.replace_cover, choose_dialog)
		scroll.add(imagewidget)
		choose_dialog.vbox.pack_start(scroll, False, False, 0)
		searchexpander = gtk.expander_new_with_mnemonic(_("Edit search terms"))
		vbox = gtk.VBox()
		hbox1 = gtk.HBox()
		artistlabel = gtk.Label(_("Artist") + ": ")
		hbox1.pack_start(artistlabel)
		self.remote_artistentry = gtk.Entry()
		self.tooltips.set_tip(self.remote_artistentry, _("Press enter to search for these terms."))
		self.remote_artistentry.connect('activate', self.choose_image_update)
		hbox1.pack_start(self.remote_artistentry, True, True, 5)
		hbox2 = gtk.HBox()
		albumlabel = gtk.Label(_("Album") + ": ")
		hbox2.pack_start(albumlabel)
		self.remote_albumentry = gtk.Entry()
		self.tooltips.set_tip(self.remote_albumentry, _("Press enter to search for these terms."))
		self.remote_albumentry.connect('activate', self.choose_image_update)
		hbox2.pack_start(self.remote_albumentry, True, True, 5)
		self.set_label_widths_equal([artistlabel, albumlabel])
		artistlabel.set_alignment(1, 0.5)
		albumlabel.set_alignment(1, 0.5)
		vbox.pack_start(hbox1)
		vbox.pack_start(hbox2)
		searchexpander.add(vbox)
		choose_dialog.vbox.pack_start(searchexpander, True, True, 0)
		choose_dialog.connect('response', self.choose_image_response, imagewidget, choose_dialog)
		choose_dialog.show_all()
		self.chooseimage_visible = True
		self.remotefilelist = []
		self.remote_artist = getattr(self.songinfo, 'artist', "")
		self.remote_artist = self.remote_artist.replace("/", "")
		self.remote_album = getattr(self.songinfo, 'album', "")
		self.remote_album = self.remote_album.replace("/", "")
		self.remote_artistentry.set_text(self.remote_artist)
		self.remote_albumentry.set_text(self.remote_album)
		self.allow_art_search = True
		self.choose_image_update()

	def choose_image_update(self, entry=None):
		if not self.allow_art_search:
			return
		self.allow_art_search = False
		self.stop_art_update = True
		while self.downloading_image:
			gtk.main_iteration()
		self.imagelist.clear()
		self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		thread = threading.Thread(target=self.choose_image_update2)
		thread.setDaemon(True)
		thread.start()

	def choose_image_update2(self):
		self.stop_art_update = False
		# Retrieve all images from amazon:
		artist_search = self.remote_artistentry.get_text()
		album_search = self.remote_albumentry.get_text()
		if len(artist_search) == 0 and len(album_search) == 0:
			gobject.idle_add(self.choose_image_no_artist_or_album_dialog)
			return
		filename = os.path.expanduser("~/.covers/temp/<imagenum>.jpg")
		if os.path.exists(os.path.dirname(filename)):
			removeall(os.path.dirname(filename))
		if not os.path.exists(os.path.dirname(filename)):
			os.mkdir(os.path.dirname(filename))
		imgfound = self.download_image_to_filename(artist_search, album_search, filename, True, True)
		self.change_cursor(None)
		if self.chooseimage_visible:
			if not imgfound:
				gobject.idle_add(self.choose_image_no_art_found)
				self.allow_art_search = True
		self.call_gc_collect = True

	def choose_image_no_artist_or_album_dialog(self):
		self.imagelist.append([0, gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, 1, 1), _("No artist or album name found.")])

	def choose_image_no_art_found(self):
		self.imagelist.append([0, gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, 1, 1), _("No cover art found.")])

	def choose_image_dialog_response(self, dialog, response_id):
		dialog.destroy()

	def choose_image_response(self, dialog, response_id, imagewidget, choose_dialog):
		self.stop_art_update = True
		if response_id == gtk.RESPONSE_ACCEPT:
			try:
				self.replace_cover(imagewidget, imagewidget.get_selected_items()[0], choose_dialog)
			except:
				pass
		self.change_cursor(None)
		self.chooseimage_visible = False
		dialog.destroy()

	def replace_cover(self, iconview, path, dialog):
		self.stop_art_update = True
		image_num = int(path[0])
		if len(self.remotefilelist) > 0:
			filename = self.remotefilelist[image_num]
			dest_filename = os.path.expanduser("~/.covers/" + self.remote_artist + "-" + self.remote_album + ".jpg")
			if os.path.exists(filename):
				# Move temp file to actual file:
				try:
					os.remove(dest_filename)
				except:
					pass
				os.rename(filename, dest_filename)
				# And finally, set the image in the interface:
				self.lastalbumart = None
				self.update_album_art()
				# Clean up..
				if os.path.exists(os.path.dirname(filename)):
					removeall(os.path.dirname(filename))
		self.chooseimage_visible = False
		dialog.destroy()
		while self.downloading_image:
			gtk.main_iteration()

	def trayaction_menu(self, status_icon, button, activate_time):
		self.traymenu.popup(None, None, None, button, activate_time)

	def trayaction_activate(self, status_icon):
		# Clicking on a gtk.StatusIcon:
		if not self.ignore_toggle_signal:
			# This prevents the user clicking twice in a row quickly
			# and having the second click not revert to the intial
			# state
			self.ignore_toggle_signal = True
			prev_state = self.UIManager.get_widget('/traymenu/showmenu').get_active()
			self.UIManager.get_widget('/traymenu/showmenu').set_active(not prev_state)
			if self.window.window.get_state() & gtk.gdk.WINDOW_STATE_WITHDRAWN: # window is hidden
				self.withdraw_app_undo()
			elif not (self.window.window.get_state() & gtk.gdk.WINDOW_STATE_WITHDRAWN): # window is showing
				self.withdraw_app()
			# This prevents the tooltip from popping up again until the user
			# leaves and enters the trayicon again
			#if self.traytips.notif_handler == None and self.traytips.notif_handler <> -1:
			#	self.traytips._remove_timer()
			gobject.timeout_add(100, self.set_ignore_toggle_signal_false)

	def tooltip_show_manually(self):
		# Since there is no signal to connect to when the user puts their
		# mouse over the trayicon, we will check the mouse position
		# manually and show/hide the window as appropriate. This is called
		# every iteration. Note: This should not occur if self.traytips.notif_
		# handler has a value, because that means that the tooltip is already
		# visible, and we don't want to override that setting simply because
		# the user's cursor is not over the tooltip.
		if self.traymenu.get_property('visible') and self.traytips.notif_handler <> -1:
			self.traytips._remove_timer()
		elif not self.traytips.notif_handler:
			pointer_screen, px, py, _ = self.window.get_screen().get_display().get_pointer()
			icon_screen, icon_rect, icon_orient = self.statusicon.get_geometry()
			x = icon_rect[0]
			y = icon_rect[1]
			width = icon_rect[2]
			height = icon_rect[3]
			if px >= x and px <= x+width and py >= y and py <= y+height:
				self.traytips._start_delay(self.statusicon)
			else:
				self.traytips._remove_timer()

	def trayaction(self, widget, event):
		# Clicking on an egg system tray icon:
		if event.button == 1 and not self.ignore_toggle_signal: # Left button shows/hides window(s)
			self.trayaction_activate(None)
		elif event.button == 2: # Middle button will play/pause
			if self.conn:
				self.pp(self.trayeventbox)
		elif event.button == 3: # Right button pops up menu
			self.traymenu.popup(None, None, None, event.button, event.time)
		return False
		
	def on_traytips_press(self, widget, event):
		if self.traytips.get_property('visible'):
			self.traytips._remove_timer()

	def withdraw_app_undo(self):
		self.window.move(self.x, self.y)
		if not self.expanded:
			self.notebook.set_no_show_all(True)
		self.window.show_all()
		self.window.present() # Helps to raise the window (useful against focus stealing prevention)
		self.window.grab_focus()
		self.notebook.set_no_show_all(False)
		if self.sticky:
			self.window.stick()
		self.withdrawn = False
		self.UIManager.get_widget('/traymenu/showmenu').set_active(True)

	def withdraw_app(self):
		if HAVE_EGG or HAVE_STATUS_ICON:
			self.window.hide()
			self.withdrawn = True
			self.UIManager.get_widget('/traymenu/showmenu').set_active(False)

	def withdraw_app_toggle(self, action):
		if self.ignore_toggle_signal:
			return
		self.ignore_toggle_signal = True
		if self.UIManager.get_widget('/traymenu/showmenu').get_active() == True:
			self.withdraw_app_undo()
		else:
			self.withdraw_app()
		gobject.timeout_add(500, self.set_ignore_toggle_signal_false)

	def set_ignore_toggle_signal_false(self):
		self.ignore_toggle_signal = False

	# Change volume on mousewheel over systray icon:
	def trayaction_scroll(self, widget, event):
		self.on_volumebutton_scroll(widget, event)

	def quit_activate(self, widget):
		self.window.destroy()

	def on_current_click(self, treeview, path, column):
		iter = self.currentdata.get_iter(path)
		try:
			self.conn.do.playid(self.currentdata.get_value(iter, 0))
		except:
			pass
		self.iterate_now()

	def switch_to_current(self, action):
		self.notebook.set_current_page(0)

	def switch_to_library(self, action):
		self.notebook.set_current_page(1)

	def switch_to_playlists(self, action):
		self.notebook.set_current_page(2)

	def switch_to_streams(self, action):
		self.notebook.set_current_page(3)

	def lower_volume(self, action):
		new_volume = int(self.volumescale.get_adjustment().get_value()) - 5
		if new_volume < 0:
			new_volume = 0
		self.volumescale.get_adjustment().set_value(new_volume)
		self.on_volumescale_change(self.volumescale, 0, 0)

	def raise_volume(self, action):
		new_volume = int(self.volumescale.get_adjustment().get_value()) + 5
		if new_volume > 100:
			new_volume = 100
		self.volumescale.get_adjustment().set_value(new_volume)
		self.on_volumescale_change(self.volumescale, 0, 0)

	# Volume control
	def on_volumebutton_clicked(self, widget):
		if not self.volumewindow.get_property('visible'):
			x_win, y_win = self.volumebutton.window.get_origin()
			button_rect = self.volumebutton.get_allocation()
			x_coord, y_coord = button_rect.x + x_win, button_rect.y+y_win
			width, height = button_rect.width, button_rect.height
			self.volumewindow.set_size_request(width, -1)
			self.volumewindow.move(x_coord, y_coord+height)
			self.volumewindow.present()
		else:
			self.volume_hide()
		return

	def on_volumebutton_scroll(self, widget, event):
		if self.conn:
			if event.direction == gtk.gdk.SCROLL_UP:
				self.raise_volume(None)
			elif event.direction == gtk.gdk.SCROLL_DOWN:
				self.lower_volume(None)
		return

	def on_volumescale_scroll(self, widget, event):
		if event.direction == gtk.gdk.SCROLL_UP:
			new_volume = int(self.volumescale.get_adjustment().get_value()) + 5
			if new_volume > 100:
				new_volume = 100
			self.volumescale.get_adjustment().set_value(new_volume)
		elif event.direction == gtk.gdk.SCROLL_DOWN:
			new_volume = int(self.volumescale.get_adjustment().get_value()) - 5
			if new_volume < 0:
				new_volume = 0
			self.volumescale.get_adjustment().set_value(new_volume)
		return

	def on_volumescale_change(self, obj, value, data):
		new_volume = int(obj.get_adjustment().get_value())
		self.conn.do.setvol(new_volume)
		self.iterate_now()
		return

	def volume_hide(self):
		self.volumebutton.set_active(False)
		self.volumewindow.hide()

	# Control callbacks
	def pp(self, widget):
		if self.conn and self.status:
			if self.status.state in ('stop', 'pause'):
				self.conn.do.play()
			elif self.status.state == 'play':
				self.conn.do.pause(1)
			self.iterate_now()
		return

	def stop(self, widget):
		if self.conn:
			self.conn.do.stop()
			self.iterate_now()
		return

	def prev(self, widget):
		if self.conn:
			self.conn.do.previous()
			self.iterate_now()
		return

	def next(self, widget):
		if self.conn:
			self.conn.do.next()
			self.iterate_now()
		return

	def mmpp(self, keys, key):
		self.pp(None)

	def mmstop(self, keys, key):
		self.stop(None)

	def mmprev(self, keys, key):
		self.prev(None)

	def mmnext(self, keys, key):
		self.next(None)

	def remove(self, widget):
		if self.conn:
			page_num = self.notebook.get_current_page()
			if page_num == self.TAB_CURRENT:
				model, selected = self.current_selection.get_selected_rows()
				if len(selected) == len(self.currentdata):
					# Everything is selected, clear:
					self.conn.do.clear()
				elif len(selected) > 0:
					self.conn.send.command_list_begin()
					selected.reverse()
					for path in selected:
						iter = model.get_iter(path)
						self.conn.send.deleteid(self.currentdata.get_value(iter, 0))
						# Prevents the entire playlist from refreshing:
						self.songs.pop(path[0])
						self.currentdata.remove(iter)
					self.conn.do.command_list_end()
			elif page_num == self.TAB_PLAYLISTS:
				dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_YES_NO, _("Delete the selected playlist(s)?"))
				dialog.set_title(_("Delete Playlist(s)"))
				response = dialog.run()
				if response == gtk.RESPONSE_YES:
					dialog.destroy()
					model, selected = self.playlists_selection.get_selected_rows()
					iters = [model.get_iter(path) for path in selected]
					for iter in iters:
						self.conn.do.rm(unescape_html(self.playlistsdata.get_value(iter, 1)))
					self.playlists_populate()
				else:
					dialog.destroy()
			elif page_num == self.TAB_STREAMS:
				dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_YES_NO, _("Delete the selected stream(s)?"))
				dialog.set_title(_("Delete Stream(s)"))
				response = dialog.run()
				if response == gtk.RESPONSE_YES:
					dialog.destroy()
					model, selected = self.streams_selection.get_selected_rows()
					iters = [model.get_iter(path) for path in selected]
					for iter in iters:
						stream_removed = False
						for i in range(len(self.stream_names)):
							if not stream_removed:
								if self.streamsdata.get_value(iter, 1) == escape_html(self.stream_names[i]):
									self.stream_names.pop(i)
									self.stream_uris.pop(i)
									stream_removed = True
					self.streams_populate()
				else:
					dialog.destroy()
			self.iterate_now()

	def randomize(self, widget):
		# Ironically enough, the command to turn shuffle on/off is called
		# random, and the command to randomize the playlist is called shuffle.
		self.conn.do.shuffle()
		return

	def clear(self, widget):
		if self.conn:
			self.conn.do.clear()
			self.iterate_now()
		return

	def on_repeat_clicked(self, widget):
		if self.conn:
			if widget.get_active():
				self.conn.do.repeat(1)
			else:
				self.conn.do.repeat(0)

	def on_shuffle_clicked(self, widget):
		if self.conn:
			if widget.get_active():
				self.conn.do.random(1)
			else:
				self.conn.do.random(0)

	def prefs(self, widget):
		prefswindow = gtk.Dialog(_("Preferences"), self.window, flags=gtk.DIALOG_DESTROY_WITH_PARENT)
		prefswindow.set_resizable(False)
		prefswindow.set_has_separator(False)
		hbox = gtk.HBox()
		prefsnotebook = gtk.Notebook()
		# MPD tab
		table = gtk.Table(9, 2, False)
		table.set_col_spacings(3)
		mpdlabel = gtk.Label()
		mpdlabel.set_markup('<b>' + _('MPD Connection') + '</b>')
		mpdlabel.set_alignment(0, 1)
		hostbox = gtk.HBox()
		hostlabel = gtk.Label(_("Host") + ":")
		hostlabel.set_alignment(0, 0.5)
		hostbox.pack_start(hostlabel, False, False, 0)
		hostentry = gtk.Entry()
		hostentry.set_text(str(self.host))
		hostbox.pack_start(hostentry, True, True, 10)
		portbox = gtk.HBox()
		portlabel = gtk.Label(_("Port") + ":")
		portlabel.set_alignment(0, 0.5)
		portbox.pack_start(portlabel, False, False, 0)
		portentry = gtk.Entry()
		portentry.set_text(str(self.port))
		portbox.pack_start(portentry, True, True, 10)
		dirbox = gtk.HBox()
		dirlabel = gtk.Label(_("Music dir") + ":")
		dirlabel.set_alignment(0, 0.5)
		dirbox.pack_start(dirlabel, False, False, 0)
		direntry = gtk.Entry()
		direntry.set_text(str(self.musicdir))
		dirbox.pack_start(direntry, True, True, 10)
		passwordbox = gtk.HBox()
		passwordlabel = gtk.Label(_("Password") + ":")
		passwordlabel.set_alignment(0, 0.5)
		passwordbox.pack_start(passwordlabel, False, False, 0)
		passwordentry = gtk.Entry()
		passwordentry.set_visibility(False)
		passwordentry.set_text(str(self.password))
		self.tooltips.set_tip(passwordentry, _("Leave blank if no password is required."))
		passwordbox.pack_start(passwordentry, True, True, 10)
		crossfadelabel = gtk.Label()
		crossfadelabel.set_markup('<b>' + _('Crossfade') + '</b>')
		crossfadelabel.set_alignment(0, 1)
		crossfadebox = gtk.HBox()
		crossfadecheck = gtk.CheckButton(_("Enable"))
		crossfadespin = gtk.SpinButton()
		crossfadespin.set_digits(0)
		crossfadespin.set_range(1, 30)
		crossfadespin.set_value(self.xfade)
		crossfadespin.set_numeric(True)
		crossfadespin.set_increments(1,5)
		crossfadespin.set_size_request(70,-1)
		crossfadelabel2 = gtk.Label(_("Fade length") + ":")
		crossfadelabel3 = gtk.Label(_("sec"))
		if not self.xfade_enabled:
			crossfadespin.set_sensitive(False)
			crossfadelabel2.set_sensitive(False)
			crossfadelabel3.set_sensitive(False)
			crossfadecheck.set_active(False)
		else:
			crossfadespin.set_sensitive(True)
			crossfadelabel2.set_sensitive(True)
			crossfadelabel3.set_sensitive(True)
			crossfadecheck.set_active(True)
		crossfadebox.pack_start(crossfadecheck, True, True, 0)
		crossfadebox.pack_start(crossfadelabel2, False, False, 0)
		crossfadebox.pack_start(crossfadespin, False, False, 5)
		crossfadebox.pack_start(crossfadelabel3, False, False, 0)
		crossfadecheck.connect('toggled', self.prefs_crossfadecheck_toggled, crossfadespin, crossfadelabel2, crossfadelabel3)
		self.set_label_widths_equal([hostlabel, portlabel, passwordlabel, dirlabel])
		autoconnect = gtk.CheckButton(_("Autoconnect on start"))
		autoconnect.set_active(self.autoconnect)
		connectbox = gtk.HBox()
		connectbutton = gtk.Button(" " + _("C_onnect"))
		connectbutton.set_image(gtk.image_new_from_stock(gtk.STOCK_CONNECT, gtk.ICON_SIZE_BUTTON))
		disconnectbutton = gtk.Button(" " + _("_Disconnect"))
		disconnectbutton.set_image(gtk.image_new_from_stock(gtk.STOCK_DISCONNECT, gtk.ICON_SIZE_BUTTON))
		connectbox.pack_start(connectbutton, False, False, 0)
		connectbox.pack_start(gtk.Label(), True, True, 0)
		connectbox.pack_start(disconnectbutton, False, False, 0)
		if self.conn:
			connectbutton.set_sensitive(False)
			disconnectbutton.set_sensitive(True)
		else:
			connectbutton.set_sensitive(True)
			disconnectbutton.set_sensitive(False)
		connectbutton.connect('clicked', self.connectbutton_clicked, disconnectbutton, hostentry, portentry, passwordentry)
		disconnectbutton.connect('clicked', self.disconnectbutton_clicked, connectbutton)
		table.attach(gtk.Label(), 1, 3, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 10, 0)
		table.attach(mpdlabel, 1, 3, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(gtk.Label(), 1, 3, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 10, 0)
		table.attach(hostbox, 1, 3, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(portbox, 1, 3, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(passwordbox, 1, 3, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(dirbox, 1, 3, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(autoconnect, 1, 3, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(connectbox, 1, 3, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(gtk.Label(), 1, 3, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(crossfadelabel, 1, 3, 11, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table.attach(gtk.Label(), 1, 3, 12, 13, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(crossfadebox, 1, 3, 13, 14, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table.attach(gtk.Label(), 1, 3, 14, 15, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 10, 0)
		# Display tab
		table2 = gtk.Table(7, 2, False)
		displaylabel = gtk.Label()
		displaylabel.set_markup('<b>' + _('Display') + '</b>')
		displaylabel.set_alignment(0, 1)
		display_art_hbox = gtk.HBox()
		display_art = gtk.CheckButton(_("Enable album art"))
		display_art.set_active(self.show_covers)
		display_art_hbox.pack_start(display_art)
		display_art_combo = gtk.combo_box_new_text()
		display_art_combo.append_text(_("Local only"))
		display_art_combo.append_text(_("Remote only"))
		display_art_combo.append_text(_("Local, then remote"))
		display_art_combo.append_text(_("Remote, then local"))
		display_art_combo.set_active(self.covers_pref)
		display_art_combo.set_sensitive(self.show_covers)
		display_art_hbox.pack_start(display_art_combo, False, False, 5)
		display_art.connect('toggled', self.prefs_art_toggled, display_art_combo)
		display_playback = gtk.CheckButton(_("Enable playback buttons"))
		display_playback.set_active(self.show_playback)
		display_playback.connect('toggled', self.prefs_playback_toggled)
		display_volume = gtk.CheckButton(_("Enable volume button"))
		display_volume.set_active(self.show_volume)
		display_volume.connect('toggled', self.prefs_volume_toggled)
		display_statusbar = gtk.CheckButton(_("Enable statusbar"))
		display_statusbar.set_active(self.show_statusbar)
		display_statusbar.connect('toggled', self.prefs_statusbar_toggled)
		display_lyrics = gtk.CheckButton(_("Enable lyrics"))
		display_lyrics.set_active(self.show_lyrics)
		display_lyrics.connect('toggled', self.prefs_lyrics_toggled)
		if not HAVE_WSDL:
			display_lyrics.set_sensitive(False)
		display_trayicon = gtk.CheckButton(_("Enable system tray icon"))
		display_trayicon.set_active(self.show_trayicon)
		if not HAVE_EGG and not HAVE_STATUS_ICON:
			display_trayicon.set_sensitive(False)
		displaylabel2 = gtk.Label()
		displaylabel2.set_markup('<b>' + _('Notification') + '</b>')
		displaylabel2.set_alignment(0, 1)
		display_notification = gtk.CheckButton(_("Popup notification on song changes"))
		display_notification.set_active(self.show_notification)
		notifhbox = gtk.HBox()
		notiflabel = gtk.Label('    ' + _('Display') + ':')
		notiflabel.set_alignment(1, 0.5)
		notification_options = gtk.combo_box_new_text()
		for i in self.popuptimes:
			if i == '1':
				notification_options.append_text(i + ' ' + _('second'))
			elif i != _('Entire song'):
				notification_options.append_text(i + ' ' + _('seconds'))
			else:
				notification_options.append_text(i)
		notification_options.set_active(self.popup_option)
		notification_options.connect('changed', self.prefs_notiftime_changed)
		notification_locs = gtk.combo_box_new_text()
		for i in self.popuplocations:
			notification_locs.append_text(i)
		notification_locs.set_active(self.traytips.notifications_location)
		notification_locs.connect('changed', self.prefs_notiflocation_changed)
		display_notification.connect('toggled', self.prefs_notif_toggled, notifhbox)
		notifhbox.pack_start(notiflabel, False, False, 0)
		notifhbox.pack_start(notification_options, False, False, 2)
		notifhbox.pack_start(notification_locs, False, False, 2)
		if not self.show_notification:
			notifhbox.set_sensitive(False)
		table2.attach(gtk.Label(), 1, 3, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table2.attach(displaylabel, 1, 3, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table2.attach(gtk.Label(), 1, 3, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table2.attach(display_playback, 1, 3, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table2.attach(display_volume, 1, 3, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table2.attach(display_statusbar, 1, 3, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table2.attach(display_trayicon, 1, 3, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table2.attach(display_lyrics, 1, 3, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table2.attach(display_art_hbox, 1, 3, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table2.attach(gtk.Label(), 1, 3, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table2.attach(displaylabel2, 1, 3, 11, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table2.attach(gtk.Label(), 1, 3, 12, 13, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table2.attach(display_notification, 1, 3, 13, 14, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table2.attach(notifhbox, 1, 3, 14, 15, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 45, 0)
		table2.attach(gtk.Label(), 1, 3, 15, 16, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 75, 0)
		# Behavior tab
		table3 = gtk.Table()
		behaviorlabel = gtk.Label()
		behaviorlabel.set_markup('<b>' + _('Window Behavior') + '</b>')
		behaviorlabel.set_alignment(0, 1)
		win_sticky = gtk.CheckButton(_("Show window on all workspaces"))
		win_sticky.set_active(self.sticky)
		win_ontop = gtk.CheckButton(_("Keep window above other windows"))
		win_ontop.set_active(self.ontop)
		update_start = gtk.CheckButton(_("Update MPD library on start"))
		update_start.set_active(self.update_on_start)
		self.tooltips.set_tip(update_start, _("If enabled, Sonata will automatically update your MPD library when it starts up."))
		exit_stop = gtk.CheckButton(_("Stop playback on exit"))
		exit_stop.set_active(self.stop_on_exit)
		self.tooltips.set_tip(exit_stop, _("MPD allows playback even when the client is not open. If enabled, Sonata will behave like a more conventional music player and, instead, stop playback upon exit."))
		minimize = gtk.CheckButton(_("Minimize to system tray on close"))
		minimize.set_active(self.minimize_to_systray)
		self.tooltips.set_tip(minimize, _("If enabled, closing Sonata will minimize it to the system tray. Note that it's currently impossible to detect if there actually is a system tray, so only check this if you have one."))
		display_trayicon.connect('toggled', self.prefs_trayicon_toggled, minimize)
		activate = gtk.CheckButton(_("Play enqueued files on activate"))
		activate.set_active(self.play_on_activate)
		self.tooltips.set_tip(activate, _("Automatically play enqueued items when activated via double-click or enter."))
		if HAVE_STATUS_ICON and self.statusicon.is_embedded() and self.statusicon.get_visible():
			minimize.set_sensitive(True)
		elif HAVE_EGG and self.trayicon.get_property('visible') == True:
			minimize.set_sensitive(True)
		else:
			minimize.set_sensitive(False)
		infofilebox = gtk.HBox()
		infofile_usage = gtk.CheckButton(_("Write status file:"))
		infofile_usage.set_active(self.use_infofile)
		self.tooltips.set_tip(infofile_usage, _("If enabled, Sonata will create a xmms-infopipe like file containing information about the current song. Many applications support the xmms-info file (Instant Messengers, IRC Clients...)"))
		infopath_options = gtk.Entry()
		infopath_options.set_text(self.infofile_path)
		self.tooltips.set_tip(infopath_options, _("If enabled, Sonata will create a xmms-infopipe like file containing information about the current song. Many applications support the xmms-info file (Instant Messengers, IRC Clients...)"))
		if not self.use_infofile:
			infopath_options.set_sensitive(False)
		infofile_usage.connect('toggled', self.prefs_infofile_toggled, infopath_options)
		infofilebox.pack_start(infofile_usage, False, False, 0)
		infofilebox.pack_start(infopath_options, True, True, 5)
		behaviorlabel2 = gtk.Label()
		behaviorlabel2.set_markup('<b>' + _('Miscellaneous') + '</b>')
		behaviorlabel2.set_alignment(0, 1)
		table3.attach(gtk.Label(), 1, 3, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table3.attach(behaviorlabel, 1, 3, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table3.attach(gtk.Label(), 1, 3, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table3.attach(win_sticky, 1, 3, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(win_ontop, 1, 3, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(minimize, 1, 3, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(gtk.Label(), 1, 3, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table3.attach(behaviorlabel2, 1, 3, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table3.attach(gtk.Label(), 1, 3, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table3.attach(update_start, 1, 3, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(exit_stop, 1, 3, 11, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(infofilebox, 1, 3, 12, 13, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(activate, 1, 3, 13, 14, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(gtk.Label(), 1, 3, 14, 15, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table3.attach(gtk.Label(), 1, 3, 15, 16, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 45, 0)
		# Format tab
		table4 = gtk.Table(9, 2, False)
		table4.set_col_spacings(3)
		formatlabel = gtk.Label()
		formatlabel.set_markup('<b>' + _('Song Formatting') + '</b>')
		formatlabel.set_alignment(0, 1)
		currentformatbox = gtk.HBox()
		currentlabel = gtk.Label(_("Current playlist:"))
		currentlabel.set_alignment(0, 0.5)
		currentoptions = gtk.Entry()
		currentoptions.set_text(self.currentformat)
		currentformatbox.pack_start(currentlabel, False, False, 0)
		currentformatbox.pack_start(currentoptions, False, False, 10)
		libraryformatbox = gtk.HBox()
		librarylabel = gtk.Label(_("Library:"))
		librarylabel.set_alignment(0, 0.5)
		libraryoptions = gtk.Entry()
		libraryoptions.set_text(self.libraryformat)
		libraryformatbox.pack_start(librarylabel, False, False, 0)
		libraryformatbox.pack_start(libraryoptions, False, False, 10)
		titleformatbox = gtk.HBox()
		titlelabel = gtk.Label(_("Window title:"))
		titlelabel.set_alignment(0, 0.5)
		titleoptions = gtk.Entry()
		titleoptions.set_text(self.titleformat)
		titleformatbox.pack_start(titlelabel, False, False, 0)
		titleformatbox.pack_start(titleoptions, False, False, 10)
		currsongformatbox1 = gtk.HBox()
		currsonglabel1 = gtk.Label(_("Current song line 1:"))
		currsonglabel1.set_alignment(0, 0.5)
		currsongoptions1 = gtk.Entry()
		currsongoptions1.set_text(self.currsongformat1)
		currsongformatbox1.pack_start(currsonglabel1, False, False, 0)
		currsongformatbox1.pack_start(currsongoptions1, False, False, 10)
		currsongformatbox2 = gtk.HBox()
		currsonglabel2 = gtk.Label(_("Current song line 2:"))
		currsonglabel2.set_alignment(0, 0.5)
		currsongoptions2 = gtk.Entry()
		currsongoptions2.set_text(self.currsongformat2)
		currsongformatbox2.pack_start(currsonglabel2, False, False, 0)
		currsongformatbox2.pack_start(currsongoptions2, False, False, 10)
		self.set_label_widths_equal([currentlabel, librarylabel, titlelabel, currsonglabel1, currsonglabel2])
		availableheading = gtk.Label()
		availableheading.set_markup('<small>' + _('Available options') + ':</small>')
		availableheading.set_alignment(0, 0)
		availablevbox = gtk.VBox()
		availableformatbox = gtk.HBox()
		availableformatting = gtk.Label()
		availableformatting.set_markup('<small><span font_family="Monospace">%A</span> - ' + _('Artist name') + '\n<span font_family="Monospace">%B</span> - ' + _('Album name') + '\n<span font_family="Monospace">%S</span> - ' + _('Song name') + '\n<span font_family="Monospace">%T</span> - ' + _('Track number') + '\n<span font_family="Monospace">%Y</span> - ' + _('Year') + '</small>')
		availableformatting.set_alignment(0, 0)
		availableformatting2 = gtk.Label()
		availableformatting2.set_markup('<small><span font_family="Monospace">%G</span> - ' + _('Genre') + '\n<span font_family="Monospace">%F</span> - ' + _('File name') + '\n<span font_family="Monospace">%P</span> - ' + _('File path') + '\n<span font_family="Monospace">%L</span> - ' + _('Song length') + '\n<span font_family="Monospace">%E</span> - ' + _('Elapsed time (title only)') + '</small>')
		availableformatting2.set_alignment(0, 0)
		availableformatbox.pack_start(availableformatting)
		availableformatbox.pack_start(availableformatting2)
		availablevbox.pack_start(availableformatbox, False, False, 0)
		enclosedtags = gtk.Label()
		enclosedtags.set_markup('<small>{ } - ' + _('Info displayed only if all enclosed tags are defined') + '</small>')
		enclosedtags.set_alignment(0,0)
		availablevbox.pack_start(enclosedtags, False, False, 4)
		table4.attach(gtk.Label(), 1, 3, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table4.attach(formatlabel, 1, 3, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table4.attach(gtk.Label(), 1, 3, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 15, 0)
		table4.attach(currentformatbox, 1, 3, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table4.attach(libraryformatbox, 1, 3, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table4.attach(titleformatbox, 1, 3, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table4.attach(currsongformatbox1, 1, 3, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table4.attach(currsongformatbox2, 1, 3, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table4.attach(gtk.Label(), 1, 3, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table4.attach(availableheading, 1, 3, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		table4.attach(availablevbox, 1, 3, 11, 12, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 45, 0)
		table4.attach(gtk.Label(), 1, 3, 12, 13, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 30, 0)
		nblabel1 = gtk.Label()
		nblabel1.set_text_with_mnemonic(_("_MPD"))
		nblabel2 = gtk.Label()
		nblabel2.set_text_with_mnemonic(_("Dis_play"))
		nblabel3 = gtk.Label()
		nblabel3.set_text_with_mnemonic(_("_Behavior"))
		nblabel4 = gtk.Label()
		nblabel4.set_text_with_mnemonic(_("_Format"))
		prefsnotebook.append_page(table, nblabel1)
		prefsnotebook.append_page(table2, nblabel2)
		prefsnotebook.append_page(table3, nblabel3)
		prefsnotebook.append_page(table4, nblabel4)
		hbox.pack_start(prefsnotebook, False, False, 10)
		prefswindow.vbox.pack_start(hbox, False, False, 10)
		close_button = prefswindow.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
		prefswindow.show_all()
		close_button.grab_focus()
		response = prefswindow.run()
		if response == gtk.RESPONSE_CLOSE:
			self.stop_on_exit = exit_stop.get_active()
			self.play_on_activate = activate.get_active()
			self.ontop = win_ontop.get_active()
			self.covers_pref = display_art_combo.get_active()
			self.sticky = win_sticky.get_active()
			self.musicdir = direntry.get_text()
			self.musicdir = os.path.expanduser(self.musicdir)
			if len(self.musicdir) > 0:
				if self.musicdir[-1] != "/":
					self.musicdir = self.musicdir + "/"
			self.minimize_to_systray = minimize.get_active()
			self.update_on_start = update_start.get_active()
			self.autoconnect = autoconnect.get_active()
			if self.currentformat != currentoptions.get_text():
				self.currentformat = currentoptions.get_text()
				self.update_playlist()
			if self.libraryformat != libraryoptions.get_text():
				self.libraryformat = libraryoptions.get_text()
				self.browse(root=self.browser.wd)
			if self.titleformat != titleoptions.get_text():
				self.titleformat = titleoptions.get_text()
				self.update_wintitle()
			if (self.currsongformat1 != currsongoptions1.get_text()) or (self.currsongformat2 != currsongoptions2.get_text()):
				self.currsongformat1 = currsongoptions1.get_text()
				self.currsongformat2 = currsongoptions2.get_text()
				self.update_cursong()
			if self.window_owner:
				if self.ontop:
					self.window.set_keep_above(True)
				else:
					self.window.set_keep_above(False)
				if self.sticky:
					self.window.stick()
				else:
					self.window.unstick()
			self.xfade = crossfadespin.get_value_as_int()
			if crossfadecheck.get_active():
				self.xfade_enabled = True
				if self.conn:
					self.conn.do.crossfade(self.xfade)
			else:
				self.xfade_enabled = False
				if self.conn:
					self.conn.do.crossfade(0)
			if self.infofile_path != infopath_options.get_text():
				self.infofile_path = os.path.expanduser(infopath_options.get_text())
 				if self.use_infofile: self.update_infofile()
			if hostentry.get_text() != self.host or portentry.get_text() != str(self.port) or passwordentry.get_text() != self.password:
				self.host = hostentry.get_text()
				try:
					self.port = int(portentry.get_text())
				except:
					pass
				self.password = passwordentry.get_text()
				self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
				self.conn = self.connect()
				if self.conn:
					self.iterate_time = self.iterate_time_when_connected
					self.conn.do.password(self.password)
					self.iterate_now()
				else:
					self.iterate_time = self.iterate_time_when_disconnected
					self.browserdata.clear()
			self.settings_save()
			self.change_cursor(None)
		prefswindow.destroy()

	def prefs_playback_toggled(self, button):
		if button.get_active():
			self.show_playback = True
			self.prevbutton.set_no_show_all(False)
			self.ppbutton.set_no_show_all(False)
			self.stopbutton.set_no_show_all(False)
			self.nextbutton.set_no_show_all(False)
			self.prevbutton.show_all()
			self.ppbutton.show_all()
			self.stopbutton.show_all()
			self.nextbutton.show_all()
		else:
			self.show_playback = False
			self.prevbutton.set_no_show_all(True)
			self.ppbutton.set_no_show_all(True)
			self.stopbutton.set_no_show_all(True)
			self.nextbutton.set_no_show_all(True)
			self.prevbutton.hide()
			self.ppbutton.hide()
			self.stopbutton.hide()
			self.nextbutton.hide()

	def prefs_art_toggled(self, button, art_combo):
		if button.get_active():
			art_combo.set_sensitive(True)
			self.traytips.set_size_request(350, -1)
			self.set_default_icon_for_art(True)
			self.imageeventbox.set_no_show_all(False)
			self.imageeventbox.show_all()
			self.trayalbumeventbox.set_no_show_all(False)
			self.trayalbumimage2.set_no_show_all(False)
			if self.conn and self.status and self.status.state in ['play', 'pause']:
				self.trayalbumeventbox.show_all()
				self.trayalbumimage2.show_all()
			self.show_covers = True
			self.update_cursong()
			self.update_album_art()
		else:
			art_combo.set_sensitive(False)
			self.traytips.set_size_request(250, -1)
			self.imageeventbox.set_no_show_all(True)
			self.imageeventbox.hide()
			self.trayalbumeventbox.set_no_show_all(True)
			self.trayalbumeventbox.hide()
			self.trayalbumimage2.set_no_show_all(True)
			self.trayalbumimage2.hide()
			self.show_covers = False
			self.update_cursong()

	def prefs_volume_toggled(self, button):
		if button.get_active():
			self.volumebutton.set_no_show_all(False)
			self.volumebutton.show()
			self.show_volume = True
		else:
			self.volumebutton.set_no_show_all(True)
			self.volumebutton.hide()
			self.show_volume = False
	
	def prefs_lyrics_toggled(self, button):
		if button.get_active():
			self.show_lyrics = True
			if self.infowindow_visible:
				self.infowindow_add_lyrics_tab(True)
				self.infowindow_update(update_all=True)
		else:
			self.show_lyrics = False
			if self.infowindow_visible:
				self.infowindow_remove_lyrics_tab()

	def prefs_statusbar_toggled(self, button):
		if button.get_active():
			self.statusbar.set_no_show_all(False)
			if self.expanded:
				self.statusbar.show_all()
			self.show_statusbar = True
			self.update_statusbar()
		else:
			self.statusbar.set_no_show_all(True)
			self.statusbar.hide()
			self.show_statusbar = False
			self.update_statusbar()

	def prefs_notif_toggled(self, button, notifhbox):
		if button.get_active():
			notifhbox.set_sensitive(True)
			self.show_notification = True
			self.labelnotify()
		else:
			notifhbox.set_sensitive(False)
			self.show_notification = False
			try:
				gobject.source_remove(self.traytips.notif_handler)
			except:
				pass
			self.traytips.hide()

	def prefs_crossfadecheck_toggled(self, button, combobox, label1, label2):
		if button.get_active():
			combobox.set_sensitive(True)
			label1.set_sensitive(True)
			label2.set_sensitive(True)
		else:
			combobox.set_sensitive(False)
			label1.set_sensitive(False)
			label2.set_sensitive(False)

	def prefs_trayicon_toggled(self, button, minimize):
		# Note that we update the sensitivity of the minimize
		# CheckButton to reflect if the trayicon is visible.
		if button.get_active():
			self.show_trayicon = True
			if HAVE_STATUS_ICON:
				self.statusicon.set_visible(True)
				if self.statusicon.is_embedded() and self.statusicon.get_visible():
					minimize.set_sensitive(True)
			elif HAVE_EGG:
				self.trayicon.show_all()
				if self.trayicon.get_property('visible') == True:
					minimize.set_sensitive(True)
		else:
			self.show_trayicon = False
			minimize.set_sensitive(False)
			if HAVE_STATUS_ICON:
				self.statusicon.set_visible(False)
			elif HAVE_EGG:
				self.trayicon.hide_all()

	def prefs_notiflocation_changed(self, combobox):
		self.traytips.notifications_location = combobox.get_active()
		self.labelnotify()

	def prefs_notiftime_changed(self, combobox):
		self.popup_option = combobox.get_active()
		self.labelnotify()

	def prefs_infofile_toggled(self, button, infofileformatbox):
		if button.get_active():
			infofileformatbox.set_sensitive(True)
			self.use_infofile = True
 			self.update_infofile()
		else:
			infofileformatbox.set_sensitive(False)
			self.use_infofile = False

	def seek(self, song, seektime):
		self.conn.do.seek(song, seektime)
		self.iterate_now()
		return

	def on_notebook_click(self, widget, event):
		if event.button == 1:
			self.volume_hide()

	def on_notebook_page_change(self, notebook, page, page_num):
		if page_num == self.TAB_CURRENT:
			gobject.idle_add(self.give_widget_focus, self.current)
		elif page_num == self.TAB_LIBRARY:
			gobject.idle_add(self.give_widget_focus, self.browser)
		elif page_num == self.TAB_PLAYLISTS:
			gobject.idle_add(self.give_widget_focus, self.playlists)
		elif page_num == self.TAB_STREAMS:
			gobject.idle_add(self.give_widget_focus, self.streams)
		gobject.idle_add(self.set_menu_contextual_items_visible)

	def on_searchtext_click(self, widget, event):
		if event.button == 1:
			self.volume_hide()

	def on_window_click(self, widget, event):
		if event.button == 1:
			self.volume_hide()
		elif event.button == 3:
			self.popup_menu(self.window, event)

	def popup_menu(self, widget, event):
		if widget == self.window:
			if event.get_coords()[1] > self.notebook.get_allocation()[1]:
				return
		if event.button == 3:
			self.set_menu_contextual_items_hidden()
			self.UIManager.get_widget('/mainmenu/songinfo_menu/').show()
			self.mainmenu.popup(None, None, None, event.button, event.time)

	def on_search_activate(self, entry):
		searchby = self.search_terms_mpd[self.searchcombo.get_active()]
		if self.searchtext.get_text() != "":
			list = self.conn.do.search(searchby, self.searchtext.get_text())
			self.browserdata.clear()
			for item in list:
				if item.type == 'directory':
					name = item.directory.split('/')[-1]
					self.browserdata.append([gtk.STOCK_OPEN, item.directory, escape_html(name)])
				elif item.type == 'file':
					self.browserdata.append(['sonata', item.file, self.parse_formatting(self.libraryformat, item, True)])
			self.browser.grab_focus()
			self.browser.scroll_to_point(0, 0)
			self.searchbutton.show()
			self.searchbutton.set_no_show_all(False)
		else:
			self.on_search_end(None)

	def on_search_end(self, button):
		self.searchbutton.hide()
		self.searchbutton.set_no_show_all(True)
		self.searchtext.set_text("")
		self.browse(root=self.browser.wd)
		self.browser.grab_focus()

	def search_mode_enabled(self):
		if self.searchbutton.get_property('visible'):
			return True
		else:
			return False

	def set_menu_contextual_items_visible(self):
		self.set_menu_contextual_items_hidden()
		if not self.expanded:
			return
		elif self.notebook.get_current_page() == self.TAB_CURRENT:
			if len(self.currentdata) > 0:
				if self.current_selection.count_selected_rows() > 0:
					self.UIManager.get_widget('/mainmenu/removemenu/').show()
					if HAVE_TAGPY:
						self.UIManager.get_widget('/mainmenu/edittagmenu/').show()
				self.UIManager.get_widget('/mainmenu/clearmenu/').show()
				self.UIManager.get_widget('/mainmenu/savemenu/').show()
				self.UIManager.get_widget('/mainmenu/sortmenu/').show()
		elif self.notebook.get_current_page() == self.TAB_LIBRARY:
			if len(self.browserdata) > 0:
				if self.browser_selection.count_selected_rows() > 0:
					self.UIManager.get_widget('/mainmenu/addmenu/').show()
					self.UIManager.get_widget('/mainmenu/replacemenu/').show()
					if HAVE_TAGPY:
						self.UIManager.get_widget('/mainmenu/edittagmenu/').show()
				self.UIManager.get_widget('/mainmenu/updatemenu/').show()
		elif self.notebook.get_current_page() == self.TAB_PLAYLISTS:
			if self.playlists_selection.count_selected_rows() > 0:
				self.UIManager.get_widget('/mainmenu/addmenu/').show()
				self.UIManager.get_widget('/mainmenu/replacemenu/').show()
				self.UIManager.get_widget('/mainmenu/rmmenu/').show()
		elif self.notebook.get_current_page() == self.TAB_STREAMS:
			if self.streams_selection.count_selected_rows() > 0:
				if self.streams_selection.count_selected_rows() == 1:
					self.UIManager.get_widget('/mainmenu/editmenu/').show()
				self.UIManager.get_widget('/mainmenu/addmenu/').show()
				self.UIManager.get_widget('/mainmenu/replacemenu/').show()
				self.UIManager.get_widget('/mainmenu/rmmenu/').show()
			self.UIManager.get_widget('/mainmenu/newmenu/').show()

	def set_menu_contextual_items_hidden(self):
		self.UIManager.get_widget('/mainmenu/removemenu/').hide()
		self.UIManager.get_widget('/mainmenu/clearmenu/').hide()
		self.UIManager.get_widget('/mainmenu/savemenu/').hide()
		self.UIManager.get_widget('/mainmenu/addmenu/').hide()
		self.UIManager.get_widget('/mainmenu/replacemenu/').hide()
		self.UIManager.get_widget('/mainmenu/rmmenu/').hide()
		self.UIManager.get_widget('/mainmenu/updatemenu/').hide()
		self.UIManager.get_widget('/mainmenu/newmenu/').hide()
		self.UIManager.get_widget('/mainmenu/editmenu/').hide()
		self.UIManager.get_widget('/mainmenu/sortmenu/').hide()
		self.UIManager.get_widget('/mainmenu/edittagmenu/').hide()
		self.UIManager.get_widget('/mainmenu/songinfo_menu/').hide()

	def find_path(self, filename):
		if HAVE_SUGAR:
			full_filename = os.path.join(sugar.env.get_bundle_path(), 'share', filename)
		else:
			if os.path.exists(os.path.join(sys.prefix, 'share', 'pixmaps', filename)):
				full_filename = os.path.join(sys.prefix, 'share', 'pixmaps', filename)
			elif os.path.exists(os.path.join(os.path.split(__file__)[0], filename)):
				full_filename = os.path.join(os.path.split(__file__)[0], filename)
			elif os.path.exists(os.path.join(os.path.split(__file__)[0], 'pixmaps', filename)):
				full_filename = os.path.join(os.path.split(__file__)[0], 'pixmaps', filename)
			elif os.path.exists(os.path.join(os.path.split(__file__)[0], 'share', filename)):
	 			full_filename = os.path.join(os.path.split(__file__)[0], 'share', filename)
			elif os.path.exists(os.path.join(__file__.split('/lib')[0], 'share', 'pixmaps', filename)):
	 			full_filename = os.path.join(__file__.split('/lib')[0], 'share', 'pixmaps', filename)
 		return full_filename
 	
 	def on_edittag_click(self, widget):
 		mpdpath = self.songinfo.file
 		self.edit_tags(widget, mpdpath)

	def edit_tags(self, widget, mpdpath=None):
		if not os.path.isdir(self.musicdir):
			error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _("The path") + " " + self.musicdir + " " + _("does not exist. Please specify a valid music directory in preferences."))
			error_dialog.set_title(_("Edit Tags"))
			error_dialog.connect('response', self.choose_image_dialog_response)
			error_dialog.show()
			return
		self.change_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
		while gtk.events_pending():
			gtk.main_iteration()
		files = []
		temp_mpdpaths = []
		if mpdpath is not None:
			# Use current file in songinfo:
			files.append(self.musicdir + mpdpath)
			temp_mpdpaths.append(mpdpath)
		elif self.notebook.get_current_page() == self.TAB_LIBRARY:
			# Populates files array with selected library items:
			items = self.browser_get_selected_items_recursive(False)
			for item in items:
				files.append(self.musicdir + item)
				temp_mpdpaths.append(item)
		elif self.notebook.get_current_page() == self.TAB_CURRENT:
			# Populates files array with selected current playlist items:
			model, selected = self.current_selection.get_selected_rows()
			for path in selected:
				item = self.songs[path[0]].file
				files.append(self.musicdir + item)
				temp_mpdpaths.append(item)
		# Initialize tags:
		tags = []
		for filenum in range(len(files)):
			tags.append({'title':'', 'artist':'', 'album':'', 'year':'', 'track':'', 'genre':'', 'comment':'', 'title-changed':False, 'artist-changed':False, 'album-changed':False, 'year-changed':False, 'track-changed':False, 'genre-changed':False, 'comment-changed':False, 'fullpath':files[filenum], 'mpdpath':temp_mpdpaths[filenum]})
		self.tagnum = -1
		if self.edit_next_tag(tags) == False:
			self.change_cursor(None)
			error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _("No music files with editable tags found."))
			error_dialog.set_title(_("Edit Tags"))
			error_dialog.connect('response', self.choose_image_dialog_response)
			error_dialog.show()
			return
		if mpdpath is None:
			editwindow = gtk.Dialog("", self.window, gtk.DIALOG_MODAL)
		else:
			editwindow = gtk.Dialog("", self.infowindow, gtk.DIALOG_MODAL)
		editwindow.set_size_request(375, -1)
		editwindow.set_resizable(False)
		editwindow.set_has_separator(False)
		table = gtk.Table(9, 2, False)
		table.set_row_spacings(2)
		filelabel = gtk.Label()
		filelabel.set_selectable(True)
		filelabel.set_line_wrap(True)
		filelabel.set_alignment(0, 0.5)
		filehbox = gtk.HBox()
		sonataicon = gtk.image_new_from_stock('sonata', gtk.ICON_SIZE_DND)
		sonataicon.set_alignment(1, 0.5)
		blanklabel = gtk.Label()
		blanklabel.set_size_request(15, 12)
		filehbox.pack_start(sonataicon, False, False, 2)
		filehbox.pack_start(filelabel, True, True, 2)
		filehbox.pack_start(blanklabel, False, False, 2)
		titlelabel = gtk.Label(_("Title") + ":")
		titlelabel.set_alignment(1, 0.5)
		titleentry = gtk.Entry()
		titlebutton = gtk.Button()
		titlebuttonvbox = gtk.VBox()
		self.editwindow_create_applyall_button(titlebutton, titlebuttonvbox, titleentry)
		titlehbox = gtk.HBox()
		titlehbox.pack_start(titlelabel, False, False, 2)
		titlehbox.pack_start(titleentry, True, True, 2)
		titlehbox.pack_start(titlebuttonvbox, False, False, 2)
		artistlabel = gtk.Label(_("Artist") + ":")
		artistlabel.set_alignment(1, 0.5)
		artistentry = gtk.Entry()
		artisthbox = gtk.HBox()
		artistbutton = gtk.Button()
		artistbuttonvbox = gtk.VBox()
		self.editwindow_create_applyall_button(artistbutton, artistbuttonvbox, artistentry)
		artisthbox.pack_start(artistlabel, False, False, 2)
		artisthbox.pack_start(artistentry, True, True, 2)
		artisthbox.pack_start(artistbuttonvbox, False, False, 2)
		albumlabel = gtk.Label(_("Album") + ":")
		albumlabel.set_alignment(1, 0.5)
		albumentry = gtk.Entry()
		albumhbox = gtk.HBox()
		albumbutton = gtk.Button()
		albumbuttonvbox = gtk.VBox()
		self.editwindow_create_applyall_button(albumbutton, albumbuttonvbox, albumentry)
		albumhbox.pack_start(albumlabel, False, False, 2)
		albumhbox.pack_start(albumentry, True, True, 2)
		albumhbox.pack_start(albumbuttonvbox, False, False, 2)
		yearlabel = gtk.Label("  " + _("Year") + ":")
		yearlabel.set_alignment(1, 0.5)
		yearentry = gtk.Entry()
		yearentry.set_size_request(50, -1)
		handlerid = yearentry.connect("insert_text", self.entry_float, True)
 		yearentry.set_data('handlerid', handlerid)
		tracklabel = gtk.Label("  " + _("Track") + ":")
		tracklabel.set_alignment(1, 0.5)
		trackentry = gtk.Entry()
		trackentry.set_size_request(50, -1)
		handlerid2 = trackentry.connect("insert_text", self.entry_float, False)
 		trackentry.set_data('handlerid2', handlerid2)
		yearbutton = gtk.Button()
		yearbuttonvbox = gtk.VBox()
		self.editwindow_create_applyall_button(yearbutton, yearbuttonvbox, yearentry)
		trackbutton = gtk.Button()
		trackbuttonvbox = gtk.VBox()
		self.editwindow_create_applyall_button(trackbutton, trackbuttonvbox, trackentry, True)
		yearandtrackhbox = gtk.HBox()
		yearandtrackhbox.pack_start(yearlabel, False, False, 2)
		yearandtrackhbox.pack_start(yearentry, True, True, 2)
		yearandtrackhbox.pack_start(yearbuttonvbox, False, False, 2)
		yearandtrackhbox.pack_start(tracklabel, False, False, 2)
		yearandtrackhbox.pack_start(trackentry, True, True, 2)
		yearandtrackhbox.pack_start(trackbuttonvbox, False, False, 2)
		genrelabel = gtk.Label(_("Genre") + ":")
		genrelabel.set_alignment(1, 0.5)
		genrecombo = gtk.combo_box_entry_new_text()
		genrecombo.set_wrap_width(2)
		self.editwindow_populate_genre_combo(genrecombo)
		genreentry = genrecombo.get_child()
		genrehbox = gtk.HBox()
		genrebutton = gtk.Button()
		genrebuttonvbox = gtk.VBox()
		self.editwindow_create_applyall_button(genrebutton, genrebuttonvbox, genreentry)
		genrehbox.pack_start(genrelabel, False, False, 2)
		genrehbox.pack_start(genrecombo, True, True, 2)
		genrehbox.pack_start(genrebuttonvbox, False, False, 2)
		commentlabel = gtk.Label(_("Comment") + ":")
		commentlabel.set_alignment(1, 0.5)
		commententry = gtk.Entry()
		commenthbox = gtk.HBox()
		commentbutton = gtk.Button()
		commentbuttonvbox = gtk.VBox()
		self.editwindow_create_applyall_button(commentbutton, commentbuttonvbox, commententry)
		commenthbox.pack_start(commentlabel, False, False, 2)
		commenthbox.pack_start(commententry, True, True, 2)
		commenthbox.pack_start(commentbuttonvbox, False, False, 2)
		self.set_label_widths_equal([titlelabel, artistlabel, albumlabel, yearlabel, genrelabel, commentlabel, sonataicon])
		genrecombo.set_size_request(-1, titleentry.size_request()[1])
		table.attach(gtk.Label(), 1, 2, 1, 2, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(filehbox, 1, 2, 2, 3, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(gtk.Label(), 1, 2, 3, 4, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(titlehbox, 1, 2, 4, 5, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(artisthbox, 1, 2, 5, 6, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(albumhbox, 1, 2, 6, 7, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(yearandtrackhbox, 1, 2, 7, 8, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(genrehbox, 1, 2, 8, 9, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(commenthbox, 1, 2, 9, 10, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		table.attach(gtk.Label(), 1, 2, 10, 11, gtk.FILL|gtk.EXPAND, gtk.FILL|gtk.EXPAND, 2, 0)
		editwindow.vbox.pack_start(table)
		#saveall_button = gtk.Button(_("Save _All"))
		#editwindow.action_area.pack_start(saveall_button)
		#editwindow.action_area.pack_start(gtk.Label())
		cancelbutton = editwindow.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT)
		savebutton = editwindow.add_button(gtk.STOCK_SAVE, gtk.RESPONSE_ACCEPT)
		editwindow.connect('delete_event', self.editwindow_hide)
		self.edit_style_orig = titleentry.get_style()
		entries = [titleentry, artistentry, albumentry, yearentry, trackentry, genreentry, commententry, filelabel]
		buttons = [titlebutton, artistbutton, albumbutton, yearbutton, trackbutton, genrebutton, commentbutton]
		entries_names = ["title", "artist", "album", "year", "track", "genre", "comment"]
		editwindow.connect('response', self.editwindow_response, tags, entries, entries_names)
		#saveall_button.connect('clicked', self.editwindow_save_all, editwindow, tags, entries, entries_names)
		for i in range(len(entries)-2):
			entries[i].connect('changed', self.edit_entry_changed)
		for i in range(len(buttons)):
			buttons[i].connect('clicked', self.editwindow_applyall, entries_names[i], tags, entries)
		self.editwindow_update(editwindow, tags, entries, entries_names)
		self.change_cursor(None)
		entries[7].set_size_request(editwindow.size_request()[0] - titlelabel.size_request()[0] - 50, -1)
		editwindow.show_all()
	
	def edit_next_tag(self, tags):
		# Returns true if next tag found (and self.tagnum is updated).
		# If no next tag found, returns False.
		while self.tagnum < len(tags)-1:
			self.tagnum = self.tagnum + 1
			if os.path.exists(tags[self.tagnum]['fullpath']):
				try:
					fileref = tagpy.FileRef(tags[self.tagnum]['fullpath'])
					if not fileref.isNull():
						return True
				except:
					pass
		return False
	
	def edit_entry_changed(self, editable):
		if not self.updating_edit_entries:
			style = editable.get_style().copy()
			style.text[gtk.STATE_NORMAL] = editable.get_colormap().alloc_color("red")
			editable.set_style(style)
	
	def edit_entry_revert_color(self, editable):
		editable.set_style(self.edit_style_orig)
	
	def editwindow_create_applyall_button(self, button, vbox, entry, autotrack=False):
		button.set_size_request(12, 12)
		if autotrack:
			self.tooltips.set_tip(button, _("Increment each selected music file, starting at track 1 for this file."))
		else:
			self.tooltips.set_tip(button, _("Apply to all selected music files."))
		padding = int((entry.size_request()[1] - button.size_request()[1])/2)+1
		vbox.pack_start(button, False, False, padding)
	
	def editwindow_applyall(self, button, item, tags, entries):
		tagnum = 0
		for tag in tags:
			tagnum = tagnum + 1
			if item == "title":
				tag['title'] = entries[0].get_text()
				tag['title-changed'] = True
			elif item == "album":
				tag['album'] = entries[2].get_text()
				tag['album-changed'] = True
			elif item == "artist":
				tag['artist'] = entries[1].get_text()
				tag['artist-changed'] = True
			elif item == "year":
				if len(entries[3].get_text()) > 0:
					tag['year'] = int(entries[3].get_text())
				else:
					tag['year'] = 0
				tag['year-changed'] = True
			elif item == "track":
				if tagnum >= self.tagnum-1:
					# Start the current song at track 1, as opposed to the first
					# song in the list.
					tag['track'] = tagnum - self.tagnum
				tag['track-changed'] = True
			elif item == "genre":
				tag['genre'] = entries[5].get_text()
				tag['genre-changed'] = True
			elif item == "comment":
				tag['comment'] = entries[6].get_text()
				tag['comment-changed'] = True
		if item == "track":
			# Update the entry for the current song:
			entries[4].set_text(str(tags[self.tagnum]['track']))
	
	def editwindow_update(self, window, tags, entries, entries_names):
		self.updating_edit_entries = True
		# Populate tags(). Note that we only retrieve info from the
		# file if the info hasn't already been changed:
		fileref = tagpy.FileRef(tags[self.tagnum]['fullpath'])
		if not tags[self.tagnum]['title-changed']:
			tags[self.tagnum]['title'] = fileref.tag().title
		if not tags[self.tagnum]['artist-changed']:
			tags[self.tagnum]['artist'] = fileref.tag().artist
		if not tags[self.tagnum]['album-changed']:
			tags[self.tagnum]['album'] = fileref.tag().album
		if not tags[self.tagnum]['year-changed']:
			tags[self.tagnum]['year'] = fileref.tag().year
		if not tags[self.tagnum]['track-changed']:
			tags[self.tagnum]['track'] = fileref.tag().track
		if not tags[self.tagnum]['genre-changed']:
			tags[self.tagnum]['genre'] = fileref.tag().genre
		if not tags[self.tagnum]['comment-changed']:
			tags[self.tagnum]['comment'] = fileref.tag().comment
		# Update interface:
		entries[0].set_text(self.tagpy_get_tag(tags[self.tagnum], 'title'))
		entries[1].set_text(self.tagpy_get_tag(tags[self.tagnum], 'artist'))
		entries[2].set_text(self.tagpy_get_tag(tags[self.tagnum], 'album'))
		if self.tagpy_get_tag(tags[self.tagnum], 'year') != 0:
			entries[3].set_text(str(self.tagpy_get_tag(tags[self.tagnum], 'year')))
		else:
			entries[3].set_text('')
		if self.tagpy_get_tag(tags[self.tagnum], 'track') != 0:
			entries[4].set_text(str(self.tagpy_get_tag(tags[self.tagnum], 'track')))
		else:
			entries[4].set_text('')
		entries[5].set_text(self.tagpy_get_tag(tags[self.tagnum], 'genre'))
		entries[6].set_text(self.tagpy_get_tag(tags[self.tagnum], 'comment'))
		entries[7].set_text(tags[self.tagnum]['mpdpath'].split('/')[-1])
		entries[0].select_region(0, len(entries[0].get_text()))
		entries[0].grab_focus()
		window.set_title(_("Edit Tags" + " - " + str(self.tagnum+1) + " " + _("of") + " " + str(len(tags))))
		self.updating_edit_entries = False
		# Update text colors as appropriate:
		for i in range(len(entries)-1):
			if tags[self.tagnum][entries_names[i] + '-changed']:
				self.edit_entry_changed(entries[i])
			else:
				self.edit_entry_revert_color(entries[i])
		gobject.idle_add(window.action_area.set_sensitive, True)

	def tagpy_get_tag(self, tag, field):
		# Since tagpy went through an API change from 0.90.1 to 0.91, we'll
		# implement both methods of retrieving the tag:
		if self.tagpy_is_91 is None:
			try:
				test = tag[field]()
				self.tagpy_is_91 = False
			except:
				self.tagpy_is_91 = True
		if self.tagpy_is_91 == False:
			return tag[field]()
		else:
			return tag[field]
	
	def tagpy_set_tag(self, tag, field, value):
		# Since tagpy went through an API change from 0.90.1 to 0.91, we'll
		# implement both methods of setting the tag:
		if field=='artist':
			if self.tagpy_is_91 == False:
				tag.setArtist(value)
			else:
				tag.artist = value
		elif field=='title':
			if self.tagpy_is_91 == False:
				tag.setTitle(value)
			else:
				tag.title = value
		elif field=='album':
			if self.tagpy_is_91 == False:
				tag.setAlbum(value)
			else:
				tag.album = value
		elif field=='year':
			if self.tagpy_is_91 == False:
				tag.setYear(int(value))
			else:
				tag.year = int(value)
		elif field=='track':
			if self.tagpy_is_91 == False:
				tag.setTrack(int(value))
			else:
				tag.track = int(value)
		elif field=='genre':
			if self.tagpy_is_91 == False:
				tag.setGenre(value)
			else:
				tag.genre = value
		elif field=='comment':
			if self.tagpy_is_91 == False:
				tag.setComment(value)
			else:
				tag.comment = value

	def editwindow_save_all(self, button, window, tags, entries, entries_names):
		while window.get_property('visible'):
			self.editwindow_response(window, gtk.RESPONSE_ACCEPT, tags, entries, entries_names)

	def editwindow_response(self, window, response, tags, entries, entries_names):
		if response == gtk.RESPONSE_REJECT:
			self.editwindow_hide(window)
		elif response == gtk.RESPONSE_ACCEPT:
			window.action_area.set_sensitive(False)
			while window.action_area.get_property("sensitive") == True or gtk.events_pending():
				gtk.main_iteration()
			filetag = tagpy.FileRef(tags[self.tagnum]['fullpath'])
			self.tagpy_set_tag(filetag.tag(), 'title', entries[0].get_text())
			self.tagpy_set_tag(filetag.tag(), 'artist', entries[1].get_text())
			self.tagpy_set_tag(filetag.tag(), 'album', entries[2].get_text())
			if len(entries[3].get_text()) > 0:
				self.tagpy_set_tag(filetag.tag(), 'year', entries[3].get_text())
			else:
				self.tagpy_set_tag(filetag.tag(), 'year', 0)
			if len(entries[4].get_text()) > 0:
				self.tagpy_set_tag(filetag.tag(), 'track', entries[4].get_text())
			else:
				self.tagpy_set_tag(filetag.tag(), 'track', 0)
			self.tagpy_set_tag(filetag.tag(), 'genre', entries[5].get_text())
			self.tagpy_set_tag(filetag.tag(), 'comment', entries[6].get_text())
			save_success = filetag.save()
			if save_success:
				if self.conn:
					if self.status:
						while self.status.get('updating_db', 0):
							gtk.main_iteration()
					self.conn.do.update(tags[self.tagnum]['mpdpath'])
			else:
				error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _("Unable to save tag to music file."))
				error_dialog.set_title(_("Edit Tags"))
				error_dialog.connect('response', self.choose_image_dialog_response)
				error_dialog.show()
			if self.edit_next_tag(tags):
				# Next file:
				gobject.timeout_add(250, self.editwindow_update, window, tags, entries, entries_names)
			else:
				# No more (valid) files:
				self.editwindow_hide(window)
	
	def editwindow_hide(self, window, data=None):
		window.destroy()
	
	def editwindow_populate_genre_combo(self, genrecombo):
		genres = ["", "A Cappella", "Acid", "Acid Jazz", "Acid Punk", "Acoustic", "Alt. Rock", "Alternative", "Ambient", "Anime", "Avantgarde", "Ballad", "Bass", "Beat", "Bebob", "Big Band", "Black Metal", "Bluegrass", "Blues", "Booty Bass", "BritPop", "Cabaret", "Celtic", "Chamber music", "Chanson", "Chorus", "Christian Gangsta Rap", "Christian Rap", "Christian Rock", "Classic Rock", "Classical", "Club", "Club-House", "Comedy", "Contemporary Christian", "Country", "Crossover", "Cult", "Dance", "Dance Hall", "Darkwave", "Death Metal", "Disco", "Dream", "Drum &amp; Bass", "Drum Solo", "Duet", "Easy Listening", "Electronic", "Ethnic", "Euro-House", "Euro-Techno", "Eurodance", "Fast Fusion", "Folk", "Folk-Rock", "Folklore", "Freestyle", "Funk", "Fusion", "Game", "Gangsta", "Goa", "Gospel", "Gothic", "Gothic Rock", "Grunge", "Hard Rock", "Hardcore", "Heavy Metal", "Hip-Hop", "House", "Humour", "Indie", "Industrial", "Instrumental", "Instrumental pop", "Instrumental rock", "JPop", "Jazz", "Jazz+Funk", "Jungle", "Latin", "Lo-Fi", "Meditative", "Merengue", "Metal", "Musical", "National Folk", "Native American", "Negerpunk", "New Age", "New Wave", "Noise", "Oldies", "Opera", "Other", "Polka", "Polsk Punk", "Pop", "Pop-Folk", "Pop/Funk", "Porn Groove", "Power Ballad", "Pranks", "Primus", "Progressive Rock", "Psychedelic", "Psychedelic Rock", "Punk", "Punk Rock", "R&amp;B", "Rap", "Rave", "Reggae", "Retro", "Revival", "Rhythmic soul", "Rock", "Rock &amp; Roll", "Salsa", "Samba", "Satire", "Showtunes", "Ska", "Slow Jam", "Slow Rock", "Sonata", "Soul", "Sound Clip", "Soundtrack", "Southern Rock", "Space", "Speech", "Swing", "Symphonic Rock", "Symphony", "Synthpop", "Tango", "Techno", "Techno-Industrial", "Terror", "Thrash Metal", "Top 40", "Trailer"]
		for genre in genres:
			genrecombo.append_text(genre)
	
	def set_label_widths_equal(self, labels):
		max_label_width = 0
		for label in labels:
			if label.size_request()[0] > max_label_width: max_label_width = label.size_request()[0]
		for label in labels:
			label.set_size_request(max_label_width, -1)

	def entry_float(self, entry, new_text, new_text_length, position, isyearlabel):
		lst_old_string = list(entry.get_chars(0, -1))
		_pos = entry.get_position()
		lst_new_string = lst_old_string.insert(_pos, new_text)
		_string = "".join(lst_old_string)
		if isyearlabel:
			_hid = entry.get_data('handlerid')
		else:
			_hid = entry.get_data('handlerid2')
		entry.handler_block(_hid)
		try:
			_val = float(_string)
			if (isyearlabel and _val <= 9999) or not isyearlabel:
				_pos = entry.insert_text(new_text, _pos)
		except StandardError, e:
			pass
		entry.handler_unblock(_hid)
		gobject.idle_add(lambda t: t.set_position(t.get_position()+1), entry)
		entry.stop_emission("insert-text")
		pass
    
	def about(self, action):
		self.about_dialog = gtk.AboutDialog()
		try:
			self.about_dialog.set_transient_for(self.window)
			self.about_dialog.set_modal(True)
		except:
			pass
		self.about_dialog.set_name('Sonata')
		self.about_dialog.set_version(__version__)
		commentlabel = _('An elegant music player for MPD.')
		self.about_dialog.set_comments(commentlabel)
		if self.conn:
			# Include MPD stats:
			stats = self.conn.do.stats()
			statslabel = stats.songs + ' ' + _('songs.') + '\n'
			statslabel = statslabel + stats.albums + ' ' + _('albums.') + '\n'
			statslabel = statslabel + stats.artists + ' ' + _('artists.') + '\n'
			try:
				hours_of_playtime = convert_time(float(stats.db_playtime)).split(':')[-3]
			except:
				hours_of_playtime = '0'
			statslabel = statslabel + hours_of_playtime + ' ' + _('hours of bliss.')
			self.about_dialog.set_copyright(statslabel)
		self.about_dialog.set_license(__license__)
		self.about_dialog.set_authors(['Scott Horowitz <stonecrest@gmail.com>'])
		self.about_dialog.set_translator_credits('fr - Floreal M <florealm@gmail.com>\npl - Tomasz Dominikowski <dominikowski@gmail.com>\nde - Paul Johnson <thrillerator@googlemail.com>\nuk - Господарисько Тарас <dogmaton@gmail.com>\nru - Beekeybee <bkb.box@bk.ru>')
		gtk.about_dialog_set_url_hook(self.show_website, "http://sonata.berlios.de")
		self.about_dialog.set_website_label("http://sonata.berlios.de")
		large_icon = gtk.gdk.pixbuf_new_from_file(self.find_path('sonata_large.png'))
		self.about_dialog.set_logo(large_icon)
		self.about_dialog.connect('response', self.about_close)
		self.about_dialog.connect('delete_event', self.about_close)
		self.about_dialog.show_all()

	def about_close(self, event, data=None):
		self.about_dialog.hide()
		return True

	def show_website(self, dialog, blah, link):
		self.browser_load(link)

	def initialize_systrayicon(self):
		# Make system tray 'icon' to sit in the system tray
		if HAVE_STATUS_ICON:
			self.statusicon = gtk.StatusIcon()
			self.statusicon.set_from_stock('sonata')
			self.statusicon.set_visible(self.show_trayicon)
			self.statusicon.connect('popup_menu', self.trayaction_menu)
			self.statusicon.connect('activate', self.trayaction_activate)
		elif HAVE_EGG:
			self.trayeventbox = gtk.EventBox()
			self.trayeventbox.connect('button_press_event', self.trayaction)
			self.trayeventbox.connect('scroll-event', self.trayaction_scroll)
			self.traytips.set_tip(self.trayeventbox)
			self.trayimage = gtk.Image()
			self.trayimage.set_from_stock('sonata', gtk.ICON_SIZE_BUTTON)
			self.trayeventbox.add(self.trayimage)
			try:
				self.trayicon = egg.trayicon.TrayIcon("TrayIcon")
				self.trayicon.add(self.trayeventbox)
				if self.show_trayicon:
					self.trayicon.show_all()
				else:
					self.trayicon.hide_all()
			except:
				pass

	def browser_load(self, docslink):
		try:
			pid = subprocess.Popen(["gnome-open", docslink]).pid
		except:
			try:
				pid = subprocess.Popen(["exo-open", docslink]).pid
			except:
				try:
					pid = subprocess.Popen(["kfmclient", "openURL", docslink]).pid
				except:
					try:
						pid = subprocess.Popen(["firefox", docslink]).pid
					except:
						try:
							pid = subprocess.Popen(["mozilla", docslink]).pid
						except:
							try:
								pid = subprocess.Popen(["opera", docslink]).pid
							except:
								error_dialog = gtk.MessageDialog(self.window, gtk.DIALOG_MODAL, gtk.MESSAGE_WARNING, gtk.BUTTONS_CLOSE, _('Unable to launch a suitable browser.'))
								error_dialog.run()
								error_dialog.destroy()

	def main(self):
		gtk.main()

class TrayIconTips(gtk.Window):
	"""Custom tooltips derived from gtk.Window() that allow for markup text and multiple widgets, e.g. a progress bar. ;)"""
	MARGIN = 4

	def __init__(self, widget=None):
		gtk.Window.__init__(self, gtk.WINDOW_POPUP)
		# from gtktooltips.c:gtk_tooltips_force_window
		self.set_app_paintable(True)
		self.set_resizable(False)
		self.set_name("gtk-tooltips")
		self.connect('expose-event', self._on__expose_event)

		if widget != None:
			self._label = gtk.Label()
			self.add(self._label)

		self._show_timeout_id = -1
		self.timer_tag = None
		self.notif_handler = None
		self.use_notifications_location = False
		self.notifications_location = 0

	def _calculate_pos(self, widget):
		if HAVE_STATUS_ICON:
			icon_screen, icon_rect, icon_orient = widget.get_geometry()
			x = icon_rect[0]
			y = icon_rect[1]
			width = icon_rect[2]
			height = icon_rect[3]
		else:
			try:
				x, y = widget.window.get_origin()
				if widget.flags() & gtk.NO_WINDOW:
					x += widget.allocation.x
					y += widget.allocation.y
				width = widget.allocation.width
				height = widget.allocation.height
			except:
				pass
		w, h = self.size_request()

		screen = self.get_screen()
		pointer_screen, px, py, _ = screen.get_display().get_pointer()
		if pointer_screen != screen:
			px = x
			py = y
		try:
			# Use the monitor that the systemtray icon is on
			monitor_num = screen.get_monitor_at_point(x, y)
		except:
			# No systemtray icon, use the monitor that the pointer is on
			monitor_num = screen.get_monitor_at_point(px, py)
		monitor = screen.get_monitor_geometry(monitor_num)

		try:
			# If the tooltip goes off the screen horizontally, realign it so that
			# it all displays.
			if (x + w) > monitor.x + monitor.width:
				x = monitor.x + monitor.width - w
			# If the tooltip goes off the screen vertically (i.e. the system tray
			# icon is on the bottom of the screen), realign the icon so that it
			# shows above the icon.
			if ((y + h + height + self.MARGIN) >
				monitor.y + monitor.height):
				y = y - h - self.MARGIN
			else:
				y = y + height + self.MARGIN
		except:
			pass

		if self.use_notifications_location == False:
			try:
				return x, y
			except:
				#Fallback to top-left:
				return monitor.x, monitor.y
		elif self.notifications_location == 0:
			try:
				return x, y
			except:
				#Fallback to top-left:
				return monitor.x, monitor.y
		elif self.notifications_location == 1:
			return monitor.x, monitor.y
		elif self.notifications_location == 2:
			return monitor.x + monitor.width - w, monitor.y
		elif self.notifications_location == 3:
			return monitor.x, monitor.y + monitor.height - h
		elif self.notifications_location == 4:
			return monitor.x + monitor.width - w, monitor.y + monitor.height - h

	def _event_handler (self, widget):
		widget.connect_after("event-after", self._motion_cb)

	def _motion_cb (self, widget, event):
		if self.notif_handler != None:
			return
		if event.type == gtk.gdk.LEAVE_NOTIFY:
			self._remove_timer()
		if event.type == gtk.gdk.ENTER_NOTIFY:
			self._start_delay(widget)

	def _start_delay (self, widget):
		self.timer_tag = gobject.timeout_add(500, self._tips_timeout, widget)

	def _tips_timeout (self, widget):
		self.use_notifications_location = False
		self._real_display(widget)

	def _remove_timer(self):
		self.hide()
		if self.timer_tag:
			gobject.source_remove(self.timer_tag)
		self.timer_tag = None

	# from gtktooltips.c:gtk_tooltips_paint_window
	def _on__expose_event(self, window, event):
		w, h = window.size_request()
		window.style.paint_flat_box(window.window,
									gtk.STATE_NORMAL, gtk.SHADOW_OUT,
									None, window, "tooltip",
									0, 0, w, h)
		return False

	def _real_display(self, widget):
		x, y = self._calculate_pos(widget)
		self.move(x, y)
		self.show()

	# Public API

	def set_text(self, text):
		self._label.set_text(text)

	def hide(self):
		gtk.Window.hide(self)
		gobject.source_remove(self._show_timeout_id)
		self._show_timeout_id = -1
		self.notif_handler = None

	def display(self, widget):
		if not self._label.get_text():
			return

		if self._show_timeout_id != -1:
			return

		self._show_timeout_id = gobject.timeout_add(500, self._real_display, widget)

	def set_tip (self, widget):
		self.widget = widget
		self._event_handler (self.widget)

	def add_widget (self, widget_to_add):
		self.widget_to_add = widget_to_add
		self.add(self.widget_to_add)

if __name__ == "__main__":
	base = Base()
	gtk.gdk.threads_enter()
	base.main()
	gtk.gdk.threads_leave()

def convert_time(raw):
	# Converts raw time to 'hh:mm:ss' with leading zeros as appropriate
	h, m, s = ['%02d' % c for c in (raw/3600, (raw%3600)/60, raw%60)]
	if h == '00':
		if m.startswith('0'):
			m = m[1:]
		return m + ':' + s
	else:
		if h.startswith('0'):
			h = h[1:]
		return h + ':' + m + ':' + s

def make_bold(s):
	if not (s.startswith('<b>') and s.endswith('</b>')):
		return '<b>%s</b>' % s
	else:
		return s

def make_unbold(s):
	if s.startswith('<b>') and s.endswith('</b>'):
		return s[3:-4]
	else:
		return s

def escape_html(s):
	s = s.replace('&', '&amp;')
	s = s.replace('<', '&lt;')
	s = s.replace('>', '&gt;')
	return s

def unescape_html(s):
	s = s.replace('&amp;', '&')
	s = s.replace('&lt;', '<')
	s = s.replace('&gt;', '>')
	return s

def rmgeneric(path, __func__):
	try:
		__func__(path)
	except OSError, (errno, strerror):
		pass

def is_binary(f):
	if '\0' in f: # found null byte
		return True
	return False

def removeall(path):
	if not os.path.isdir(path):
		return

	files=os.listdir(path)

	for x in files:
		fullpath=os.path.join(path, x)
		if os.path.isfile(fullpath):
			f=os.remove
			rmgeneric(fullpath, f)
		elif os.path.isdir(fullpath):
			removeall(fullpath)
			f=os.rmdir
			rmgeneric(fullpath, f)

def remove_list_duplicates(inputlist, inputlist2=[], case_sensitive=True):
	# If inputlist2 is provided, keep it synced with inputlist.
	# Note that this is only implemented if case_sensitive=False.
	# Also note that we do this manually instead of using list(set(x))
	# so that the inputlist order is preserved.
	if len(inputlist2) > 0:
		sync_lists = True
	else:
		sync_lists = False
	outputlist = []
	outputlist2 = []
	for i in range(len(inputlist)):
		dup = False
		# Search outputlist from the end, since the inputlist is typically in
		# alphabetical order
		j = len(outputlist)-1
		if case_sensitive:
			while j >= 0:
				if inputlist[i] == outputlist[j]:
					dup = True
					break
				j = j - 1
		elif sync_lists:
			while j >= 0:
				if inputlist[i].lower() == outputlist[j].lower() and inputlist2[i].lower() == outputlist2[j].lower():
					dup = True
					break
				j = j - 1
		else:
			while j >= 0:
				if inputlist[i].lower() == outputlist[j].lower():
					dup = True
					break
				j = j - 1
		if not dup:
			outputlist.append(inputlist[i])
			if sync_lists:
				outputlist2.append(inputlist2[i])
	return (outputlist, outputlist2)

def start_dbus_interface(toggle=False):
	if HAVE_DBUS:
		exit_now = False
		try:
			session_bus = dbus.SessionBus()
			bus = dbus.SessionBus()
			retval = dbus.dbus_bindings.bus_request_name(session_bus.get_connection(), "org.MPD.Sonata", dbus.dbus_bindings.NAME_FLAG_DO_NOT_QUEUE)
			if retval in (dbus.dbus_bindings.REQUEST_NAME_REPLY_PRIMARY_OWNER, dbus.dbus_bindings.REQUEST_NAME_REPLY_ALREADY_OWNER):
				pass
			elif retval in (dbus.dbus_bindings.REQUEST_NAME_REPLY_EXISTS, dbus.dbus_bindings.REQUEST_NAME_REPLY_IN_QUEUE):
				exit_now = True
		except:
			print _("Sonata failed to connect to the D-BUS session bus: Unable to determine the address of the message bus (try 'man dbus-launch' and 'man dbus-daemon' for help)")
		if exit_now:
			obj = dbus.SessionBus().get_object('org.MPD', '/org/MPD/Sonata')
			if toggle:
				obj.toggle(dbus_interface='org.MPD.SonataInterface')
			else:
				print _("An instance of Sonata is already running.")
				obj.show(dbus_interface='org.MPD.SonataInterface')
			sys.exit()

if HAVE_DBUS:
	class BaseDBus(dbus.service.Object, Base):
		def __init__(self, bus_name, object_path, window=None, sugar=False):
			dbus.service.Object.__init__(self, bus_name, object_path)
			Base.__init__(self, window, sugar)

		@dbus.service.method('org.MPD.SonataInterface')
		def show(self):
			self.window.hide()
			self.withdraw_app_undo()

		@dbus.service.method('org.MPD.SonataInterface')
		def toggle(self):
			if self.window.get_property('visible'):
				self.withdraw_app()
			else:
				self.withdraw_app_undo()
