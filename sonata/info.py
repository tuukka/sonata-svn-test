
import sys, os, locale, urllib
import threading # get_lyrics_start starts a thread get_lyrics_thread
from socket import getdefaulttimeout as socketgettimeout
from socket import setdefaulttimeout as socketsettimeout

import gtk, gobject
ServiceProxy = None # importing tried when needed

import ui, misc
import mpdhelper as mpdh
from consts import consts

class Info(object):
	def __init__(self, config, info_image, linkcolor, on_link_click_cb, library_return_search_items, get_playing_song, TAB_INFO, on_image_activate, on_image_motion_cb, on_image_drop_cb, album_return_artist_and_tracks, new_tab):
		self.config = config
		self.info_image = info_image
		self.linkcolor = linkcolor
		self.on_link_click_cb = on_link_click_cb
		self.library_return_search_items = library_return_search_items
		self.get_playing_song = get_playing_song
		self.on_image_activate = on_image_activate
		self.on_image_motion_cb = on_image_motion_cb
		self.on_image_drop_cb = on_image_drop_cb
		self.album_return_artist_and_tracks = album_return_artist_and_tracks

		try:
			self.enc = locale.getpreferredencoding()
		except:
			print "Locale cannot be found; please set your system's locale. Aborting..."
			sys.exit(1)

		self.lyricServer = None
		self.last_info_bitrate = None

		self.info_boxes_in_more = None
		self.info_editlabel = None
		self.info_editlyricslabel = None
		self.info_labels = None
		self.info_left_label = None
		self.info_lyrics = None
		self.info_morelabel = None
		self.info_searchlabel = None
		self.info_tagbox = None
		self.info_type = None

		self.lyricsText = None
		self.albumText = None

		# Info tab
		self.info_area = ui.scrollwindow(shadow=gtk.SHADOW_NONE)

		if self.config.info_art_enlarged:
			self.info_imagebox = ui.eventbox()
		else:
			self.info_imagebox = ui.eventbox(w=152)

		self.info_imagebox.add(self.info_image)

		self.tab = new_tab(self.info_area, gtk.STOCK_JUSTIFY_FILL, TAB_INFO, self.info_area)

		self.info_imagebox.drag_dest_set(gtk.DEST_DEFAULT_HIGHLIGHT | gtk.DEST_DEFAULT_DROP, [("text/uri-list", 0, 80), ("text/plain", 0, 80)], gtk.gdk.ACTION_DEFAULT)
		self.info_imagebox.connect('button_press_event', self.on_image_activate)
		self.info_imagebox.connect('drag_motion', self.on_image_motion_cb)
		self.info_imagebox.connect('drag_data_received', self.on_image_drop_cb)

		self.widgets_initialize(self.info_area)

	def widgets_initialize(self, info_scrollwindow):

		vert_spacing = 1
		horiz_spacing = 2
		margin = 5
		outter_hbox = gtk.HBox()
		outter_vbox = gtk.VBox()

		# Song info
		info_song = ui.expander(markup="<b>" + _("Song Info") + "</b>", expand=self.config.info_song_expanded, can_focus=False)
		info_song.connect("activate", self.info_expanded, "song")
		inner_hbox = gtk.HBox()

		inner_hbox.pack_start(self.info_imagebox, False, False, horiz_spacing)

		self.info_tagbox = gtk.VBox()

		labels_left = []
		self.info_type = {}
		self.info_labels = []
		self.info_boxes_in_more = []
		labels_type = ['title', 'artist', 'album', 'date', 'track', 'genre', 'file', 'bitrate']
		labels_text = [_("Title"), _("Artist"), _("Album"), _("Date"), _("Track"), _("Genre"), _("File"), _("Bitrate")]
		labels_link = [False, True, True, False, False, False, False, False]
		labels_tooltip = ["", _("Launch artist in Wikipedia"), _("Launch album in Wikipedia"), "", "", "", "", ""]
		labels_in_more = [False, False, False, False, False, False, True, True]
		for i in range(len(labels_text)):
			self.info_type[labels_text[i]] = i
			tmphbox = gtk.HBox()
			if labels_in_more[i]:
				self.info_boxes_in_more += [tmphbox]
			tmplabel = ui.label(markup="<b>" + labels_text[i] + ":</b>", y=0)
			if i == 0:
				self.info_left_label = tmplabel
			if not labels_link[i]:
				tmplabel2 = ui.label(wrap=True, y=0, select=True)
			else:
				# Using set_selectable overrides the hover cursor that sonata
				# tries to set for the links, and I can't figure out how to
				# stop that. So we'll disable set_selectable for these two
				# labels until it's figured out.
				tmplabel2 = ui.label(wrap=True, y=0, select=False)
			if labels_link[i]:
				tmpevbox = ui.eventbox(add=tmplabel2)
				self.info_apply_link_signals(tmpevbox, labels_type[i], labels_tooltip[i])
			tmphbox.pack_start(tmplabel, False, False, horiz_spacing)
			if labels_link[i]:
				tmphbox.pack_start(tmpevbox, False, False, horiz_spacing)
			else:
				tmphbox.pack_start(tmplabel2, False, False, horiz_spacing)
			self.info_labels += [tmplabel2]
			labels_left += [tmplabel]
			self.info_tagbox.pack_start(tmphbox, False, False, vert_spacing)
		ui.set_widths_equal(labels_left)
		
		mischbox = gtk.HBox()
		self.info_morelabel = ui.label(y=0)
		moreevbox = ui.eventbox(add=self.info_morelabel)
		self.info_apply_link_signals(moreevbox, 'more', _("Toggle extra tags"))
		self.info_editlabel = ui.label(y=0)
		editevbox = ui.eventbox(add=self.info_editlabel)
		self.info_apply_link_signals(editevbox, 'edit', _("Edit song tags"))
		mischbox.pack_start(moreevbox, False, False, horiz_spacing)
		mischbox.pack_start(editevbox, False, False, horiz_spacing)

		self.info_tagbox.pack_start(mischbox, False, False, vert_spacing)
		inner_hbox.pack_start(self.info_tagbox, False, False, horiz_spacing)
		info_song.add(inner_hbox)
		outter_vbox.pack_start(info_song, False, False, margin)
		
		# Lyrics
		self.info_lyrics = ui.expander(markup="<b>" + _("Lyrics") + "</b>", expand=self.config.info_lyrics_expanded, can_focus=False)
		self.info_lyrics.connect("activate", self.info_expanded, "lyrics")
		lyricsbox = gtk.VBox()
		lyricsbox_top = gtk.HBox()
		self.lyricsText = ui.label(markup=" ", y=0, select=True, wrap=True)
		lyricsbox_top.pack_start(self.lyricsText, True, True, horiz_spacing)
		lyricsbox.pack_start(lyricsbox_top, True, True, vert_spacing)
		lyricsbox_bottom = gtk.HBox()
		self.info_searchlabel = ui.label(y=0)
		self.info_editlyricslabel = ui.label(y=0)
		searchevbox = ui.eventbox(add=self.info_searchlabel)
		editlyricsevbox = ui.eventbox(add=self.info_editlyricslabel)
		self.info_apply_link_signals(searchevbox, 'search', _("Search Lyricwiki.org for lyrics"))
		self.info_apply_link_signals(editlyricsevbox, 'editlyrics', _("Edit lyrics at Lyricwiki.org"))
		lyricsbox_bottom.pack_start(searchevbox, False, False, horiz_spacing)
		lyricsbox_bottom.pack_start(editlyricsevbox, False, False, horiz_spacing)
		lyricsbox.pack_start(lyricsbox_bottom, False, False, vert_spacing)
		self.info_lyrics.add(lyricsbox)
		outter_vbox.pack_start(self.info_lyrics, False, False, margin)
		
		# Album info
		info_album = ui.expander(markup="<b>" + _("Album Info") + "</b>", expand=self.config.info_album_expanded, can_focus=False)
		info_album.connect("activate", self.info_expanded, "album")
		albumbox = gtk.VBox()
		albumbox_top = gtk.HBox()
		self.albumText = ui.label(markup=" ", y=0, select=True, wrap=True)
		albumbox_top.pack_start(self.albumText, False, False, horiz_spacing)
		albumbox.pack_start(albumbox_top, False, False, vert_spacing)
		info_album.add(albumbox)
		outter_vbox.pack_start(info_album, False, False, margin)
		
		# Finish..
		if not self.config.show_lyrics:
			ui.hide(self.info_lyrics)
		if not self.config.show_covers:
			ui.hide(self.info_imagebox)
		# self.config.info_song_more will be overridden on on_link_click, so
		# store it in a temporary var..
		temp = self.config.info_song_more
		self.on_link_click(moreevbox, None, 'more')
		self.config.info_song_more = temp
		if self.config.info_song_more:
			self.on_link_click(moreevbox, None, 'more')
		outter_hbox.pack_start(outter_vbox, False, False, margin)
		info_scrollwindow.add_with_viewport(outter_hbox)

	def get_widgets(self):
		return self.info_area

	def get_info_imagebox(self):
		return self.info_imagebox

	def show_lyrics_updated(self):
		if self.config.show_lyrics:
			ui.show(self.info_lyrics)
		else:
			ui.hide(self.info_lyrics)

	def info_apply_link_signals(self, widget, linktype, tooltip):
		widget.connect("enter-notify-event", self.on_link_enter)
		widget.connect("leave-notify-event", self.on_link_leave)
		widget.connect("button-press-event", self.on_link_click, linktype)
		widget.set_tooltip_text(tooltip)

	def on_link_enter(self, widget, _event):
		if widget.get_children()[0].get_use_markup():
			ui.change_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))
		
	def on_link_leave(self, _widget, _event):
		ui.change_cursor(None)
	
	def on_link_click(self, _widget, _event, linktype):
		if linktype == 'more':
			previous_is_more = (self.info_morelabel.get_text() == "(" + _("more") + ")")
			if previous_is_more:
				self.info_morelabel.set_markup(misc.link_markup(_("hide"), True, True, self.linkcolor))
				self.config.info_song_more = True
			else:
				self.info_morelabel.set_markup(misc.link_markup(_("more"), True, True, self.linkcolor))
				self.config.info_song_more = False
			if self.config.info_song_more:
				for hbox in self.info_boxes_in_more:
					ui.show(hbox)
			else:
				for hbox in self.info_boxes_in_more:
					ui.hide(hbox)
		else:
			self.on_link_click_cb(linktype)

	def info_expanded(self, expander, infotype):
		expanded = not expander.get_expanded()
		if infotype == "song":
			self.config.info_song_expanded = expanded
		elif infotype == "lyrics":
			self.config.info_lyrics_expanded = expanded
		elif infotype == "album":
			self.config.info_album_expanded = expanded

	def info_update(self, playing_or_paused, newbitrate, songinfo, update_all, blank_window=False, skip_lyrics=False):
		# update_all = True means that every tag should update. This is
		# only the case on song and status changes. Otherwise we only
		# want to update the minimum number of widgets so the user can
		# do things like select label text.
		if playing_or_paused:
			bitratelabel = self.info_labels[self.info_type[_("Bitrate")]]
			titlelabel = self.info_labels[self.info_type[_("Title")]]
			artistlabel = self.info_labels[self.info_type[_("Artist")]]
			albumlabel = self.info_labels[self.info_type[_("Album")]]
			datelabel = self.info_labels[self.info_type[_("Date")]]
			genrelabel = self.info_labels[self.info_type[_("Genre")]]
			tracklabel = self.info_labels[self.info_type[_("Track")]]
			filelabel = self.info_labels[self.info_type[_("File")]]
			if not self.last_info_bitrate or self.last_info_bitrate != newbitrate:
				bitratelabel.set_text(newbitrate)
			self.last_info_bitrate = newbitrate
			if update_all:
				# Use artist/album Wikipedia links?
				artist_use_link = False
				if 'artist' in songinfo:
					artist_use_link = True
				album_use_link = False
				if 'album' in songinfo:
					album_use_link = True
				titlelabel.set_text(mpdh.get(songinfo, 'title'))
				if artist_use_link:
					artistlabel.set_markup(misc.link_markup(misc.escape_html(mpdh.get(songinfo, 'artist')), False, False, self.linkcolor))
				else:
					artistlabel.set_text(mpdh.get(songinfo, 'artist'))
				if album_use_link:
					albumlabel.set_markup(misc.link_markup(misc.escape_html(mpdh.get(songinfo, 'album')), False, False, self.linkcolor))
				else:
					albumlabel.set_text(mpdh.get(songinfo, 'album'))
				datelabel.set_text(mpdh.get(songinfo, 'date'))
				genrelabel.set_text(mpdh.get(songinfo, 'genre'))
				if 'track' in songinfo:
					tracklabel.set_text(mpdh.getnum(songinfo, 'track', '0', False, 0))
				else:
					tracklabel.set_text("")
				path = misc.file_from_utf8(self.config.musicdir[self.config.profile_num] + os.path.dirname(mpdh.get(songinfo, 'file')))
				if os.path.exists(path):
					filelabel.set_text(self.config.musicdir[self.config.profile_num] + mpdh.get(songinfo, 'file'))
					self.info_editlabel.set_markup(misc.link_markup(_("edit tags"), True, True, self.linkcolor))
				else:
					filelabel.set_text(mpdh.get(songinfo, 'file'))
					self.info_editlabel.set_text("")
				if 'album' in songinfo:
					# Update album info:
					artist, tracks = self.album_return_artist_and_tracks()
					trackinfo = ""
					album = mpdh.get(songinfo, 'album')
					year = mpdh.get(songinfo, 'date', None)
					if album is not None:
						albuminfo = album + "\n"
					playtime = 0
					if len(tracks) > 0:
						for track in tracks:
							playtime += int(mpdh.get(track, 'time', 0))
							if 'title' in track:
								trackinfo = trackinfo + mpdh.getnum(track, 'track', '0', False, 2) + '. ' + mpdh.get(track, 'title') + '\n'
							else:
								trackinfo = trackinfo + mpdh.getnum(track, 'track', '0', False, 2) + '. ' + mpdh.get(track, 'file').split('/')[-1] + '\n'
						if artist is not None:
							albuminfo += artist + "\n"
						if year is not None:
							albuminfo += year + "\n"
						albuminfo += misc.convert_time(playtime) + "\n"
						albuminfo += "\n" + trackinfo
					else:
						albuminfo = _("Album info not found.")
					self.albumText.set_markup(misc.escape_html(albuminfo))
				else:
					self.albumText.set_text(_("Album name not set."))
				# Update lyrics:
				if self.config.show_lyrics and not skip_lyrics:
					global ServiceProxy
					if ServiceProxy is None:
						try:
							from ZSI import ServiceProxy
							# Make sure we have the right version..
							_test = ServiceProxy.ServiceProxy
						except:
							ServiceProxy = None
					if ServiceProxy is None:
						self.info_searchlabel.set_text("")
						self.info_show_lyrics(_("ZSI not found, fetching lyrics support disabled."), "", "", True)
					elif 'artist' in songinfo and 'title' in songinfo:
						self.get_lyrics_start(mpdh.get(songinfo, 'artist'), mpdh.get(songinfo, 'title'), mpdh.get(songinfo, 'artist'), mpdh.get(songinfo, 'title'), os.path.dirname(mpdh.get(songinfo, 'file')))
					else:
						self.info_searchlabel.set_text("")
						self.info_show_lyrics(_("Artist or song title not set."), "", "", True)
		else:
			blank_window = True
		if blank_window:
			for label in self.info_labels:
				label.set_text("")
			self.info_editlabel.set_text("")
			if self.config.show_lyrics:
				self.info_searchlabel.set_text("")
				self.info_editlyricslabel.set_text("")
				self.info_show_lyrics("", "", "", True)
			self.albumText.set_text("")
			self.last_info_bitrate = ""

	def info_check_for_local_lyrics(self, artist, title, song_dir):
		if os.path.exists(self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_HOME)):
			return self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_HOME)
		elif os.path.exists(self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_PATH)):
			return self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_PATH)
		elif os.path.exists(self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_HOME_ALT)):
			return self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_HOME_ALT)
		elif os.path.exists(self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_PATH_ALT)):
			return self.target_lyrics_filename(artist, title, song_dir, consts.LYRICS_LOCATION_PATH_ALT)
		return None

	def get_lyrics_start(self, *args):
		lyricThread = threading.Thread(target=self.get_lyrics_thread, args=args)
		lyricThread.setDaemon(True)
		lyricThread.start()

	def lyricwiki_format(self, text):
		return urllib.quote(str(unicode(text).title()))

	def lyricwiki_editlink(self, songinfo):
		artist, title = [self.lyricwiki_format(mpdh.get(songinfo, key))
				 for key in ('artist', 'title')]
		return "http://lyricwiki.org/index.php?title=%s:%s&action=edit" % (artist, title)

	def get_lyrics_thread(self, search_artist, search_title, filename_artist, filename_title, song_dir):
		filename_artist = misc.strip_all_slashes(filename_artist)
		filename_title = misc.strip_all_slashes(filename_title)
		filename = self.info_check_for_local_lyrics(filename_artist, filename_title, song_dir)
		search_str = misc.link_markup(_("search"), True, True, self.linkcolor)
		edit_str = misc.link_markup(_("edit"), True, True, self.linkcolor)
		if filename:
			# If the lyrics only contain "not found", delete the file and try to
			# fetch new lyrics. If there is a bug in Sonata/SZI/LyricWiki that
			# prevents lyrics from being found, storing the "not found" will
			# prevent a future release from correctly fetching the lyrics.
			f = open(filename, 'r')
			lyrics = f.read()
			f.close()
			if lyrics == _("Lyrics not found"):
				misc.remove_file(filename)
				filename = self.info_check_for_local_lyrics(filename_artist, filename_title, song_dir)
		if filename:
			# Re-use lyrics from file:
			f = open(filename, 'r')
			lyrics = f.read()
			f.close()
			# Strip artist - title line from file if it exists, since we
			# now have that information visible elsewhere.
			header = filename_artist + " - " + filename_title + "\n\n"
			if lyrics[:len(header)] == header:
				lyrics = lyrics[len(header):]
			gobject.idle_add(self.info_show_lyrics, lyrics, filename_artist, filename_title)
			gobject.idle_add(self.info_searchlabel.set_markup, search_str)
			gobject.idle_add(self.info_editlyricslabel.set_markup, edit_str)
		else:
			# Use default filename:
			filename = self.target_lyrics_filename(filename_artist, filename_title, song_dir)
			# Fetch lyrics from lyricwiki.org
			gobject.idle_add(self.info_show_lyrics, _("Fetching lyrics..."), filename_artist, filename_title)
			if self.lyricServer is None:
				wsdlFile = "http://lyricwiki.org/server.php?wsdl"
				try:
					self.lyricServer = True
					timeout = socketgettimeout()
					socketsettimeout(consts.LYRIC_TIMEOUT)
					self.lyricServer = ServiceProxy.ServiceProxy(wsdlFile, cachedir=os.path.expanduser("~/.service_proxy_dir")) 
				except:
					socketsettimeout(timeout)
					lyrics = _("Couldn't connect to LyricWiki")
					gobject.idle_add(self.info_show_lyrics, lyrics, filename_artist, filename_title)
					self.lyricServer = None
					gobject.idle_add(self.info_searchlabel.set_markup, search_str)
					gobject.idle_add(self.info_editlyricslabel.set_markup, edit_str)
					return
			try:
				timeout = socketgettimeout()
				socketsettimeout(consts.LYRIC_TIMEOUT)
				lyrics = self.lyricServer.getSong(artist=self.lyricwiki_format(search_artist), song=self.lyricwiki_format(search_title))['return']["lyrics"]
				if lyrics.lower() != "not found":
					lyrics = misc.unescape_html(lyrics)
					lyrics = misc.wiki_to_html(lyrics)
					lyrics = lyrics.encode("ISO-8859-1")
					gobject.idle_add(self.info_show_lyrics, lyrics, filename_artist, filename_title)
					# Save lyrics to file:
					misc.create_dir('~/.lyrics/')
					f = open(filename, 'w')
					lyrics = misc.unescape_html(lyrics)
					try:
						f.write(lyrics.decode(self.enc).encode('utf8'))
					except:
						f.write(lyrics)
					f.close()
				else:
					lyrics = _("Lyrics not found")
					gobject.idle_add(self.info_show_lyrics, lyrics, filename_artist, filename_title)
			except:
				lyrics = _("Fetching lyrics failed")
				gobject.idle_add(self.info_show_lyrics, lyrics, filename_artist, filename_title)
			gobject.idle_add(self.info_searchlabel.set_markup, search_str)
			gobject.idle_add(self.info_editlyricslabel.set_markup, edit_str)
			socketsettimeout(timeout)

	def info_show_lyrics(self, lyrics, artist, title, force=False):
		if force:
			# For error messages where there is no appropriate artist or 
			# title, we pass force=True:
			self.lyricsText.set_text(lyrics)
		elif self.get_playing_song():
			# Verify that we are displaying the correct lyrics:
			songinfo = self.get_playing_song()
			try:
				if misc.strip_all_slashes(mpdh.get(songinfo, 'artist')) == artist and misc.strip_all_slashes(mpdh.get(songinfo, 'title')) == title:
					try:
						self.lyricsText.set_markup(misc.escape_html(lyrics))
					except:
						self.lyricsText.set_text(lyrics)
			except:
				pass

	def resize_elements(self, notebook_allocation):
		# Resize labels in info tab to prevent horiz scrollbar:
		if self.config.show_covers:
			labelwidth = notebook_allocation.width - self.info_left_label.allocation.width - self.info_imagebox.allocation.width - 60 # 60 accounts for vert scrollbar, box paddings, etc..
		else:
			labelwidth = notebook_allocation.width - self.info_left_label.allocation.width - 60 # 60 accounts for vert scrollbar, box paddings, etc..
		if labelwidth > 100:
			for label in self.info_labels:
				label.set_size_request(labelwidth, -1)
		# Resize lyrics/album gtk labels:
		labelwidth = notebook_allocation.width - 45 # 45 accounts for vert scrollbar, box paddings, etc..
		self.lyricsText.set_size_request(labelwidth, -1)
		self.albumText.set_size_request(labelwidth, -1)

	def target_lyrics_filename(self, artist, title, song_dir, force_location=None):
		# FIXME Why did we have this condition here: if self.conn:
		lyrics_loc = force_location if force_location else self.config.lyrics_location
		# Note: *_ALT searching is for compatibility with other mpd clients (like ncmpcpp):
		if lyrics_loc == consts.LYRICS_LOCATION_HOME:
			targetfile = os.path.expanduser("~/.lyrics/" + artist + "-" + title + ".txt")
		elif lyrics_loc == consts.LYRICS_LOCATION_PATH:
			targetfile = self.config.musicdir[self.config.profile_num] + song_dir + "/" + artist + "-" + title + ".txt"
		elif lyrics_loc == consts.LYRICS_LOCATION_HOME_ALT:
			targetfile = os.path.expanduser("~/.lyrics/" + artist + " - " + title + ".txt")
		elif lyrics_loc == consts.LYRICS_LOCATION_PATH_ALT:
			targetfile = self.config.musicdir[self.config.profile_num] + song_dir + "/" + artist + " - " + title + ".txt"
		targetfile = misc.file_exists_insensitive(targetfile)
		return misc.file_from_utf8(targetfile)
	
