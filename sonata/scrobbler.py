
"""
This module makes Sonata submit the songs played to a Last.fm account.

Example usage:
import scrobbler
self.scrobbler = scrobbler.Scrobbler(self.config)
self.scrobbler.import_module()
self.scrobbler.init()
...
self.scrobbler.iterate()
...
self.scrobbler.handle_change_status(False, self.prevsonginfo)
"""

import os, time
import threading # init, np, post start threads init_thread, do_np, do_post

audioscrobbler = None # imported when first needed

import mpdhelper as mpdh

class Scrobbler(object):
	def __init__(self, config):
		self.config = config

		self.scrob = None
		self.scrob_post = None
		self.scrob_start_time = ""
		self.scrob_playing_duration = 0
		self.scrob_last_prepared = ""
		self.scrob_time_now = None

		self.elapsed_now = None
	
	def import_module(self, _show_error=False):
		"""Import the audioscrobbler module"""
		# We need to try to import audioscrobbler either when the app starts (if
		# as_enabled=True) or if the user enables it in prefs.
		global audioscrobbler
		if audioscrobbler is None:
			import audioscrobbler

	def imported(self):
		"""Return True if the audioscrobbler module has been imported"""
		return audioscrobbler is not None

	def init(self):
		"""Initialize the Audioscrobbler support if enabled and configured"""
		if audioscrobbler is not None and self.config.as_enabled and len(self.config.as_username) > 0 and len(self.config.as_password_md5) > 0:
			thread = threading.Thread(target=self.init_thread)
			thread.setDaemon(True)
			thread.start()

	def init_thread(self):
		if self.scrob is None:
			self.scrob = audioscrobbler.AudioScrobbler()
		if self.scrob_post is None:
			self.scrob_post = self.scrob.post(self.config.as_username, self.config.as_password_md5, verbose=True)
		else:
			if self.scrob_post.authenticated:
				return # We are authenticated
			else:
				self.scrob_post = self.scrob.post(self.config.as_username, self.config.as_password_md5, verbose=True)
		try:
			self.scrob_post.auth()
		except Exception, e:
			print "Error authenticating audioscrobbler", e
			self.scrob_post = None
		if self.scrob_post:
			self.retrieve_cache()

	def iterate(self):
		"""Update the running time"""
		self.scrob_time_now = time.time()

	def handle_change_status(self, playing, prevsonginfo, songinfo=None, switched_from_stop_to_play=None, mpd_time_now=None):
		"""Handle changes to play status, submitting info as appropriate"""
		if prevsonginfo and prevsonginfo.has_key('time'):
			prevsong_time = mpdh.get(prevsonginfo, 'time')
		else:
			prevsong_time = None

		if playing:
			elapsed_prev = self.elapsed_now
			self.elapsed_now, length = [float(c) for c in mpd_time_now.split(':')]
			current_file = mpdh.get(songinfo, 'file')
			if switched_from_stop_to_play:
				# Switched from stop to play, prepare current track:
				self.prepare(songinfo)
			elif (prevsong_time and 
			      (self.scrob_last_prepared != current_file or 
			       (self.scrob_last_prepared == current_file and elapsed_prev and
				abs(elapsed_prev-length)<=2 and self.elapsed_now<=2 and length>0))):
				# New song is playing, post previous track if time criteria is met.
				# In order to account for the situation where the same song is played twice in
				# a row, we will check if the previous time was the end of the song and we're
				# now at the beginning of the same song.. this technically isn't right in
				# the case where a user seeks back to the beginning, but that's an edge case.
				if self.scrob_playing_duration > 4 * 60 or self.scrob_playing_duration > int(prevsong_time)/2:
					if self.scrob_start_time != "":
						self.post(prevsonginfo)
				# Prepare current track:
				self.prepare(songinfo)
			elif self.scrob_time_now:
				# Keep track of the total amount of time that the current song
				# has been playing:
				self.scrob_playing_duration += time.time() - self.scrob_time_now
		else: # stopped:
			self.elapsed_now = 0
			if prevsong_time:
				if self.scrob_playing_duration > 4 * 60 or self.scrob_playing_duration > int(prevsong_time)/2:
					# User stopped the client, post previous track if time
					# criteria is met:
					if self.scrob_start_time != "":
						self.post(prevsonginfo)

	def auth_changed(self):
		"""Try to re-authenticate"""
		if self.scrob_post:
			if self.scrob_post.authenticated:
				self.scrob_post = None

	def prepare(self, songinfo):
		if audioscrobbler is not None:
			self.scrob_start_time = ""
			self.scrob_last_prepared = ""
			self.scrob_playing_duration = 0

			if self.config.as_enabled and songinfo:
				# No need to check if the song is 30 seconds or longer,
				# audioscrobbler.py takes care of that.
				if songinfo.has_key('time'):
					self.np(songinfo)

					self.scrob_start_time = str(int(time.time()))
					self.scrob_last_prepared = mpdh.get(songinfo, 'file')
			
	def np(self, songinfo):
		thread = threading.Thread(target=self.do_np, args=(songinfo,))
		thread.setDaemon(True)
		thread.start()
				   
	def do_np(self, songinfo):
		self.init()
		if self.config.as_enabled and self.scrob_post and songinfo:
			if songinfo.has_key('artist') and \
			   songinfo.has_key('title') and \
			   songinfo.has_key('time'):
				if not songinfo.has_key('album'):
					album = u''
				else:
					album = mpdh.get(songinfo, 'album')
				if not songinfo.has_key('track'):
					tracknumber = u''
				else:
					tracknumber = mpdh.get(songinfo, 'track')
				self.scrob_post.nowplaying(mpdh.get(songinfo, 'artist'),
									 		mpdh.get(songinfo, 'title'),
								 			mpdh.get(songinfo, 'time'),
									 		tracknumber,
									 		album,
									 		self.scrob_start_time)
		time.sleep(10)
		
	def post(self, prevsonginfo):
		self.init()
		if self.config.as_enabled and self.scrob_post and prevsonginfo:
			if prevsonginfo.has_key('artist') and \
			   prevsonginfo.has_key('title') and \
			   prevsonginfo.has_key('time'):
				if not prevsonginfo.has_key('album'):
					album = u''
				else:
					album = mpdh.get(prevsonginfo, 'album')
				if not prevsonginfo.has_key('track'):
					tracknumber = u''
				else:
					tracknumber = mpdh.get(prevsonginfo, 'track')
				self.scrob_post.addtrack(mpdh.get(prevsonginfo, 'artist'),
										 		mpdh.get(prevsonginfo, 'title'),
										 		mpdh.get(prevsonginfo, 'time'),
										 		self.scrob_start_time,
										 		tracknumber,
										 		album)
										 		
				thread = threading.Thread(target=self.do_post)
				thread.setDaemon(True)
				thread.start()
		self.scrob_start_time = ""
		
	def do_post(self):
		for _i in range(0,3):
			if not self.scrob_post:
				return
			if len(self.scrob_post.cache) == 0:
				return
			try:
				self.scrob_post.post()
			except audioscrobbler.AudioScrobblerConnectionError, e:
				print e
				pass
			time.sleep(10)
	
	def save_cache(self):
		"""Save the cache in a file"""
		filename = os.path.expanduser('~/.config/sonata/ascache')
		if self.scrob_post:
			self.scrob_post.savecache(filename)
	
	def retrieve_cache(self):
		filename = os.path.expanduser('~/.config/sonata/ascache')
		if self.scrob_post:
			self.scrob_post.retrievecache(filename)
		
