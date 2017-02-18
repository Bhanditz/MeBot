#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import logging
import getpass
from optparse import OptionParser
from bs4 import BeautifulSoup
import re
import sleekxmpp
from search import Google, Wikipedia
from collections import defaultdict


def plist(t):
	if len(t) == 0:
		return 'No one is'
	if len(t) == 1:
		return t[0] + ' is'
	elif len(t) == 2:
		return ' and '.join(t) + ' are'
	elif len(t) > 2:
		return ', '.join(t[:-1]) + ', and ' + t[-1] + ' are'
	else:
		return str(t)

class User:
	def __init__(self):
		self.active = defaultdict(int)
		self.force = defaultdict(int)
		self.last_msg = ''
		self.restricted = False
		self.last_search = ''

class MeBot(sleekxmpp.ClientXMPP):
	qwords = {
		'who', 'what', 'when', 'where', 'why', 'how', 'can', 'do', 'are', 'is'
	}
	def __init__(self, jid, password):
		# Initialize sleekxmpp and plugins
		sleekxmpp.ClientXMPP.__init__(self, jid, password)
		self.register_plugin('xep_0280', module='xep_0280') # carbons
		self.register_plugin('xep_0030') # Service Discovery
		self.register_plugin('xep_0199') # XMPP Ping
		self.plugin['xep_0280'].enable(callback=self.carbon_callback)
		# Configure event handlers.
		self.add_event_handler("session_start", self.start)
		self.add_event_handler("message", self.pm_handler)
		self.add_event_handler("carbon_received", self.carbon_handler)
		self.add_event_handler("carbon_sent", self.carbon_handler)
		self.searches = {
			'google': Google(),
			'wiki': Wikipedia()
		}
		self.commands = {
			'!a': self.activate_user, '!g': self.g_command,
			'!l': self.list_active,   '!r': self.deactivate_user,
			'!m': self.more,          '!h': self.meta_help,
			'!b': self.block_user,    '!f': self.force_user,
			'!w': self.w_command
		}
		# Initialize state settings
		self.users = defaultdict(User)

	def start(self, event):
		"""
			event -- An empty dictionary. The session_start
					 event does not provide any additional
					 data.
		"""
		self.get_roster()
		self.send_presence()

	def join_muc(event):
		self.plugin['xep_0045'].joinMUC(self.room,
										self.nick,
										# password=the_room_password,
										wait=True)

	def message(self, body, msg):
		self.send_message(mto=self.recipient, mbody=body, mtype='chat')

	def carbon_callback(self, msg):
		print("Carbon callback:")
		print(msg)

	def carbon_handler(self, msg):
		try:
			self.pm_handler(msg['carbon_received'])
		except TypeError:
			self.pm_handler(msg['carbon_sent'])

	def pm_handler(self, msg):
		"""
			msg -- The received message stanza. See the documentation
				   for stanza objects and the Message stanza to see
				   how it may be used.
		"""
		if str(msg['from']).split('/')[0] == self.boundjid.bare:
			self.recipient = str(msg['to']).split('/')[0]
		else:
			self.recipient = str(msg['from']).split('/')[0]
		# For some reason carbons sent by you come twice (from gajim at least)
		if self.user().last_msg == msg:
			return
		if msg['body'][0] == '!':
			self.parse(msg)
		elif msg['body'].split()[0].lower() in self.qwords \
				or msg['body'][-1] == '?' \
				or self.user().force[str(msg['from']).split('/')[0]]:
			self.assist(msg)
		self.user().last_msg = msg

	def parse(self, msg):
		permsg = ', you are not permitted to execute commands.'
		if (self.user().restricted
				and str(msg['from']).split('/')[0] != self.boundjid.bare):
			self.message(self.recipient + permsg, msg)
			return
		try:
			self.commands[msg['body'].split()[0]](msg)
		except KeyError as e:
			if str(e)[:2] == '\'!':
				self.error(msg)
			else:
				raise

	def error(self, msg):
		self.message("%s, please use a valid command. Try !h." % msg['from'], msg)

	def meta_help(self, msg):
		self.message("""
			!g [query] - Runs a Google search for your query.
			!w [query] - Runs a Wikipedia search for your query.
			!a [user]  - Adds user to help list. Automatically answer their questions.
			!r [user]  - Removes user from help list.
			!f [user]  - (force) Toggle aggressive mode for user.
			!m - Returns more detailed results from last query.
			!l - List all users currently receiving help.
			!b - Block recipient from executing commands.
			!h - View his help.""".replace('\t', ''), msg
		)

	def activate_user(self, msg):
		self.set_user(True, msg)
	def deactivate_user(self, msg):
		self.set_user(False, msg)
	def force_user(self, msg):
		self.set_user(True, msg, force=True)

	def set_user(self, value, msg, force=False):
		s = " now" if value else " no longer"
		who = ''.join(msg['body'].split()[1:])
		if who == 'you':
			who = str(msg['to']).split('/')[0]
		elif who == 'me':
			who = str(msg['from']).split('/')[0]
		elif who == self.recipient.split('@')[0]:
			who = self.recipient
		elif who == self.boundjid.bare.split('@')[0]:
			who = self.boundjid.bare
		if who == self.boundjid.bare or who == self.recipient:
			if force:
				self.user().force[who] = \
					not self.user().force[who]
				on = "on" if self.user().force[who] else "off"
				self.message("Toggling aggressive mode {} for {}.".format(on, who), msg)
			else:
				self.user().active[who] = value
				self.message(who + s + " being helped.", msg)
		else:
			self.message("Error: Invalid user. Try 'you' or 'me.'", msg)

	def user(self):
		return self.users[self.recipient]

	def list_active(self, msg):
		active = [k for (k, v) in self.user().active.items() if v]
		self.message(plist(active) + " currently being helped.", msg)

	def block_user(self, msg):
		un = 'un' * self.user().restricted
		blocked = "blocked from executing commands."
		self.user().restricted = not self.user().restricted
		self.message(self.recipient + " is now " + un + blocked, msg)

	def g_command(self, msg):
		self.search_command('google', msg)
	def w_command(self, msg):
		self.search_command('wiki', msg)

	def search_command(self, stype, msg):
		self.user().last_search = stype
		if len(msg['body']) == 2:
			query = ' '.join(self.user().last_msg['body'].split())
		else:
			query = ' '.join(msg['body'].split()[1:])
		self.search(msg, stype, query)

	def assist(self, msg):
		if self.user().active[str(msg['from']).split('/')[0]]:
			self.search(msg, 'google', msg['body'])

	def search(self, msg, stype, query):
		self.message(self.searches[stype].search(query), msg)

	def more(self, msg):
		last = self.user().last_search
		try:
			second = msg['body'].split()[1]
		except:
			self.message(self.searches[last].more(), msg)
			return
		if second == 'all':
			self.message(self.searches[last].complete(), msg)
			return
		try:
			i = int(second)
			self.message(self.searches[last].details(i - 1), msg)
		except ValueError:
			self.message('Specify an integer, "all", or nothing.', msg)


class Setup:
	def __init__(self):
		self.optp = OptionParser()
		# Output verbosity options.
		self.optp.add_option('-q', '--quiet', help='set logging to ERROR',
							 action='store_const', dest='loglevel',
							 const=logging.ERROR, default=logging.INFO)
		self.optp.add_option('-d', '--debug', help='set logging to DEBUG',
							 action='store_const', dest='loglevel',
							 const=logging.DEBUG, default=logging.INFO)
		self.optp.add_option('-v', '--verbose', help='set logging to COMM',
							 action='store_const', dest='loglevel',
							 const=5, default=logging.INFO)
		# JID and password options.
		self.optp.add_option("-j", "--jid", dest="jid",
							 help="JID to use")
		self.optp.add_option("-p", "--password", dest="password",
							 help="password to use")

	def parse(self):
		self.opts, self.args = self.optp.parse_args()

	def prompt(self):
		if self.opts.jid is None:
			self.opts.jid = raw_input("Username: ")
		if self.opts.password is None:
			self.opts.password = getpass.getpass("Password: ")


if __name__ == '__main__':
	# Ensure UTF-8 is used for Python < 3
	if sys.version_info < (3, 0):
		reload(sys)
		sys.setdefaultencoding('utf8')
	else:
		raw_input = input
	
	# Configure options
	options = Setup()
	options.parse()
	options.prompt()
	logging.basicConfig(level=options.opts.loglevel,
						format='%(levelname)-8s %(message)s')
	
	# Setup MeBot
	xmpp = MeBot(options.opts.jid, options.opts.password)
	
	# Connect to the XMPP server and start processing XMPP stanzas.
	if xmpp.connect():
		xmpp.process(block=True)
		print("Done")
	else:
		print("Unable to connect.")
