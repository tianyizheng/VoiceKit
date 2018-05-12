#!/usr/bin/env python3
# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run a recognizer using the Google Assistant Library with button support.

The Google Assistant Library has direct access to the audio API, so this Python
code doesn't need to record audio. Hot word detection "OK, Google" is supported.

It is available for Raspberry Pi 2/3 only; Pi Zero is not supported.
"""

import logging
import platform
import sys
import threading
import subprocess
import re
from spotipy.oauth2 import SpotifyClientCredentials
import spotipy
import time

import aiy.assistant.auth_helpers
from aiy.assistant.library import Assistant
import aiy.voicehat
from google.assistant.library.event import EventType


import vlc
import youtube_dl

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
)


GET_VOLUME = r'amixer get Master | grep "Front Left:" | sed "s/.*\[\([0-9]\+\)%\].*/\1/"'
SET_VOLUME = 'amixer -q set Master %d%%'

ydl_opts = {
    'default_search': 'ytsearch1:',
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True
}
vlc_instance = vlc.get_default_instance()
vlc_player = vlc_instance.media_player_new()

id='sample'
secret='sample'

client_credentials_manager = SpotifyClientCredentials(id,secret)
sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

playList = []
playing = set([1,2,3,4])
stopForced = False

class MyAssistant(object):
    """An assistant that runs in the background.

    The Google Assistant Library event loop blocks the running thread entirely.
    To support the button trigger, we need to run the event loop in a separate
    thread. Otherwise, the on_button_pressed() method will never get a chance to
    be invoked.
    """

    def __init__(self):
        self._task = threading.Thread(target=self._run_task)
        self._can_start_conversation = False
        self._assistant = None

    def start(self):
        """Starts the assistant.

        Starts the assistant event loop and begin processing events.
        """
        self._task.start()

    def power_off_pi(self):
        aiy.audio.say('Good bye!')
        subprocess.call('sudo shutdown now', shell=True)


    def reboot_pi(self):
        aiy.audio.say('See you in a bit!')
        subprocess.call('sudo reboot', shell=True)


    def say_ip(self):
        ip_address = subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True)
        aiy.audio.say('My IP address is %s' % ip_address.decode('utf-8'))

    def set_volume(self, change):
        old_vol = subprocess.check_output(GET_VOLUME, shell=True).strip()
        try:
            logging.info("volume: %s", old_vol)
            new_vol = max(0, min(100, int(old_vol) + change))
            subprocess.call(SET_VOLUME % new_vol, shell=True)
            aiy.audio.say('Volume at %d %%.' % new_vol)
        except (ValueError, subprocess.CalledProcessError):
            logging.exception("Error using amixer to adjust volume.")

    def play_music(self, name):
        try:
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                meta = ydl.extract_info(name, download=False)
        except Exception:
            aiy.audio.say('Sorry, I can\'t find that song.')
            return

        if meta:
            info = meta['entries'][0]
            vlc_player.set_media(vlc_instance.media_new(info['url']))
            aiy.audio.say('Now playing ' + re.sub(r'[^\s\w]', '', info['title']))
            print(info['title'])
            vlc_player.play()

    def searchArtist(self, name):
      vlc_player.stop()
      platList = []
      artist = sp.search(q='artist:' + name, type='artist', limit=1)['artists']['items'][0]
      results = sp.artist_top_tracks(artist['uri'])

      for track in results['tracks'][:10]:
        if stopForced:
            break
        query = artist['name'] + ' ' + track['name']
        self.play_music(query)
        while True:
            state = vlc_player.get_state()
            if state not in playing:
                break
            continue


    def searchPlaylist(self, name):
      vlc_player.stop()
      platList = []
      pList = sp.search(q=name, type='playlist', limit=1)['playlists']['items'][0]
      userId='spotify'
      playListID=pList['id']
      tracks = sp.user_playlist(userId, playlist_id=playListID, fields='tracks(items(track(artists,name)))')['tracks']['items']
      for track in tracks:
        if stopForced:
            break
        name = track['track']['name']
        artist = track['track']['artists'][0]['name']
        query = name + ' ' + artist
        self.play_music(query)
        while True:
            state = vlc_player.get_state()
            if state not in playing:
                break
            continue


    def _run_task(self):
        credentials = aiy.assistant.auth_helpers.get_assistant_credentials()
        with Assistant(credentials) as assistant:
            self._assistant = assistant
            for event in assistant.start():
                self._process_event(event)

    def _process_event(self, event):
        status_ui = aiy.voicehat.get_status_ui()
        if event.type == EventType.ON_START_FINISHED:
            status_ui.status('ready')
            self._can_start_conversation = True
            # Start the voicehat button trigger.
            aiy.voicehat.get_button().on_press(self._on_button_pressed)
            if sys.stdout.isatty():
                print('Say "OK, Google" or press the button, then speak. '
                      'Press Ctrl+C to quit...')

        elif event.type == EventType.ON_CONVERSATION_TURN_STARTED:
            self._can_start_conversation = False
            status_ui.status('listening')

        elif event.type == EventType.ON_RECOGNIZING_SPEECH_FINISHED and event.args:
            print('You said:', event.args['text'])
            text = event.args['text'].lower()
            assistant = self._assistant
            if text == 'stop':
                if vlc_player.get_state() == vlc.State.Playing:
                    vlc_player.stop()
                    stopForced = True
            elif text == 'power off':
                assistant.stop_conversation()
                self.power_off_pi()
            elif text == 'reboot':
                assistant.stop_conversation()
                self.reboot_pi()
            elif text == 'ip address':
                assistant.stop_conversation()
                self.say_ip()
            elif text == 'pause':
                assistant.stop_conversation()
                vlc_player.set_pause(True)
            elif text == 'resume':
                assistant.stop_conversation()
                vlc_player.set_pause(False)
            elif text.startswith('play '):
                assistant.stop_conversation()
                self.play_music(text[5:])

            elif text.startswith('artist '):
                assistant.stop_conversation()
                self.searchArtist(text[7:])
            elif text.startswith('playlist '):
                assistant.stop_conversation()
                self.searchPlaylist(text[9:])

            elif text == 'volume up':
                assistant.stop_conversation()
                self.set_volume(10)
            elif text == 'volume down':
                assistant.stop_conversation()
                self.set_volume(-10)

        elif event.type == EventType.ON_END_OF_UTTERANCE:
            status_ui.status('thinking')

        elif (event.type == EventType.ON_CONVERSATION_TURN_FINISHED
              or event.type == EventType.ON_CONVERSATION_TURN_TIMEOUT
              or event.type == EventType.ON_NO_RESPONSE):
            status_ui.status('ready')
            self._can_start_conversation = True

        elif event.type == EventType.ON_ASSISTANT_ERROR and event.args and event.args['is_fatal']:
            sys.exit(1)

    def _on_button_pressed(self):
        # Check if we can start a conversation. 'self._can_start_conversation'
        # is False when either:
        # 1. The assistant library is not yet ready; OR
        # 2. The assistant library is already in a conversation.
        if self._can_start_conversation:
            self._assistant.start_conversation()


def main():
    if platform.machine() == 'armv6l':
        print('Cannot run hotword demo on Pi Zero!')
        exit(-1)
    MyAssistant().start()


if __name__ == '__main__':
    main()
