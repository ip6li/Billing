#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Copyright (c) 2016. by Christian Felsing
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.

---

billing.py - billing

https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL
https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket
https://wiki.freeswitch.org/wiki/Mod_commands
https://wiki.freeswitch.org/wiki/Event_List

Relevant sind hier die Events CHANNEL_BRIDGE und CHANNEL_UNBRIDGE, die
dem Billing System signalisieren, dass eine Verbindung auf- oder
abgebaut wurde.

Todo:

* Screening der Nummernkreise, die kostenlos sind
* Ermittlung der Verbindungskosten:
** Festnetz national
** Festnetz international
** Mobilfunk
* Sperrung Sonderrufnummern: In Gemeinschaft Call Routing
* Dokumentation der Gebuehren fuer Kassierer
'''


import ESL
import os, sys, time, atexit, re
import grp
import pwd
import signal
import time
import logging
import logging.handlers
#import lockfile
import smtplib
from email.mime.text import MIMEText


send_mail=1
smtp_from="sender@example.com"
smtp_to="recipient@example.com"
smtp_relay="localhost"


lockFileName='/var/run/billing/billing.pid'

syslog = logging.getLogger('billing')
syslog.setLevel(logging.DEBUG)
handler = logging.handlers.SysLogHandler(address = '/dev/log')
formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
handler.setFormatter(formatter)
syslog.addHandler(handler)

cadm_uid = pwd.getpwnam('gsmaster').pw_uid
cadm_home = pwd.getpwnam('gsmaster').pw_dir
cadm_gid = grp.getgrnam('gemeinschaft').gr_gid

aoc_amount="0.01"
real_amount="0.05"
ip = "192.168.106.3"



###############################################################
# Send Mail if we got money
###############################################################

def sendInfoMail(subject,body):
  msg = MIMEText(body, 'plain', 'utf-8')
  msg['Subject'] = subject
  msg['From'] = smtp_from
  msg['To'] = smtp_to

  # Send the message via our own SMTP server, but don't include the
  # envelope header.
  s = smtplib.SMTP(smtp_relay)
  s.sendmail(msg['From'], msg['To'], msg.as_string())
  s.quit()



###############################################################
# some init and signal stuff
###############################################################

def delpid():
  try:
    os.remove(lockFileName)
  except:
    syslog.info('someone already deleted '+lockFileName)


def sigterm_handler(signum, frame):
  syslog.info('billing server shutdown')
  sys.exit()


def sigint_handler(signum, frame):
  syslog.info('billing server shutdown')
  sys.exit()


def initial_program_setup_root():
  if (cadm_gid==0):
    print ("I am not willing to run in group root")
    os.exit(1)
  if (cadm_uid==0):
    print ("I am not willing to run as root")
    os.exit(1)

  signal.signal(signal.SIGTERM, sigterm_handler)
  signal.signal(signal.SIGINT,  sigint_handler)

  os.setgid(cadm_gid)
  os.setuid(cadm_uid)




###############################################################
# send AOC information
###############################################################

def sendAOC (mode, con, key, caller_ip, leg_a_uuid, leg_b_uuid, from_uri, to_uri, callid, variable_sip_full_via, variable_sip_full_from, variable_sip_full_to,variable_sip_call_id,units):
  syslog.info ("Sent AOC for "+key+" ("+caller_ip+")\n")

  if (mode=="D"):
    charging_info="subtotal"
    aoc_mode="aoc-d"
  elif (mode=="E"):
    charging_info="total"
    aoc_mode="aoc-e"
  else:
    syslog.error ("illegal mode");

  e = ESL.ESLevent("SEND_INFO")
  e.addHeader("from-uri", "sip:"+from_uri)
  e.addHeader("to-uri", "sip:"+to_uri)
  #e.addHeader("From", variable_sip_full_from);
  #e.addHeader("To", variable_sip_full_to.);
  e.addHeader("Call-ID", variable_sip_call_id);
  e.addHeader("content-type", 'application/vnd.etsi.aoc+xml');
  e.addHeader("profile", 'gemeinschaft');
  e.addHeader("content-disposition", "signal; handling=required")

  print variable_sip_full_from.decode("string-escape") + "\n"
  print variable_sip_full_to.decode("string-escape") + "\n"

  amount_subtotal=str(float(aoc_amount)*int(units));
  body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><aoc xmlns=\"http://uri.etsi.org/ngn/params/xml/simservs/aoc\"><"+aoc_mode+"><charging-info>"+charging_info+"</charging-info><recorded-charges><recorded-currency-units><currency-id>EUR</currency-id><currency-amount>"+amount_subtotal+"</currency-amount></recorded-currency-units></recorded-charges><billing-id>normal-charging</billing-id></"+aoc_mode+"></aoc>"

  e.addBody(body);
  con.sendEvent(e);

  print e.serialize()


def do_main_program():
  host="127.0.0.1"
  port="8021"
  con = ESL.ESLconnection(host, port, 'ClueCon')
  if (not con):
    syslog.error("Unable to establish connection to %s:%s",host,port)
    sys.exit(1)
  
  con.events("plain","all");
  con.filter("Event-Name","CHANNEL_BRIDGE");
  con.filter("Event-Name","CHANNEL_UNBRIDGE");
  
  timer = {}
  units = {}
  from_uri = {}
  to_uri = {}
  callid = {}
  variable_sip_full_via = {}
  variable_sip_full_from = {}
  variable_sip_full_to = {}
  variable_sip_call_id = {}
  Bridge_A_Unique_ID_list = {}
  Bridge_B_Unique_ID_list = {}
  to_list = {}
  while con.connected():
    e = con.recvEventTimed(1000)
    if e:
      if (e.getHeader("Event-Name") == "CHANNEL_BRIDGE"):
        uuid=e.getHeader("Channel-Call-UUID")
        m=re.search(';tag=(\S+)', e.getHeader("variable_sip_full_from").decode("string-escape"))
        from_tag=m.group(0)
        from_port=""
        if (e.getHeader("variable_sip_from_port")):
          from_port=":"+e.getHeader("variable_sip_from_port")
        full_from=e.getHeader("variable_sip_from_user")+"@"+e.getHeader("variable_sip_from_host")+from_port+";tag="+e.getHeader("variable_sip_from_tag")
        full_to=e.getHeader("variable_sip_to_user")+"@"+e.getHeader("variable_sip_to_host")
        if (uuid):
          print "start "+uuid+"\n"
          sip_from=e.getHeader("variable_sip_from_user_stripped")
          sip_to=e.getHeader("variable_sip_req_user")
          if (sip_from=="592"):
            if (re.match('^\+4919[89]|^0019[89]',sip_to)):
              print "eventphone number "+sip_to+"\n"
            elif (re.match('[1-9]',sip_to)):
              print "internal number "+sip_to+"\n"
            elif (re.match('^\+49800|^00800',sip_to)):
              print "free number "+sip_to+"\n"
            elif (re.match('^\+49|^00[1-9]',sip_to)):
              timer[uuid]=0
              units[uuid]=0
              from_uri[uuid]=e.getHeader("variable_sip_from_uri")
              to_uri[uuid]=e.getHeader("variable_sip_to_uri")
              callid[uuid]=e.getHeader("Call-ID")
              variable_sip_call_id[uuid]=e.getHeader("variable_sip_call_id").decode("string-escape")
              variable_sip_full_via[uuid]=e.getHeader("variable_sip_full_via").decode("string-escape")
              variable_sip_full_from[uuid]=e.getHeader("variable_sip_full_from").decode("string-escape")
              variable_sip_full_to[uuid]=e.getHeader("variable_sip_full_to").decode("string-escape")
              Bridge_A_Unique_ID_list[uuid]=e.getHeader("Bridge-A-Unique-ID")
              Bridge_B_Unique_ID_list[uuid]=e.getHeader("Bridge-B-Unique-ID")
            elif (re.match('^\+49|^00[1-9]',sip_to)):
              print "unknown profix "+sip_to+"\n"

      elif (e.getHeader("Event-Name") == "CHANNEL_UNBRIDGE"):
        uuid=e.getHeader("Channel-Call-UUID")
        if (uuid and (uuid in units)):
          subject="Telefon inkrementierte Vereinkasse"
          body='Der Bestand der Vereinskasse hat sich um %s € erhöht' % str(float(real_amount)*int(units[uuid]))
          if (send_mail):
            sendInfoMail(subject,body)
          del timer[uuid]
          del units[uuid]
          del from_uri[uuid]
          del to_uri[uuid]
          del callid[uuid]
          del variable_sip_full_via[uuid]
          del variable_sip_full_from[uuid]
          del variable_sip_full_to[uuid]
          del Bridge_A_Unique_ID_list[uuid]
          del Bridge_B_Unique_ID_list[uuid]
          print "end "+uuid+"\n"
      else:
        print "Event: "+e.getHeader("Event-Name")+"\n";
  
    for key in timer:
      new_time=int(time.time())
      oldtime=timer[key]
      if (new_time > oldtime + 60):
        timer[key]=new_time
        units[key]+=1;
        sendAOC("D",con,key,"192.168.106.7",Bridge_A_Unique_ID_list[key],Bridge_B_Unique_ID_list[key],to_uri[key],from_uri[key],callid[key],variable_sip_full_via[key],variable_sip_full_from[key],variable_sip_full_to[key],variable_sip_call_id[key],units[key])







###############################################################
# Main
###############################################################

initial_program_setup_root()

DEBUG=1

if (DEBUG):
  do_main_program()
else:

  # see http://www.jejik.com/files/examples/daemon3x.py
  try:
    with open(lockFileName,'r') as pf:
      pid = int(pf.read().strip())
  except IOError:
    pid = None

  if pid:
    message = "pidfile {0} already exist. Daemon already running?\n"
    sys.stderr.write(message.format(lockFileName))
    sys.exit(1)

  try:
    pid = os.fork()
    if pid > 0:
      # exit first parent
      sys.exit(0)
  except OSError as err:
    sys.stderr.write('fork #1 failed: {0}\n'.format(err))
    sys.exit(1)

  os.chdir("/")
  os.setsid()
  os.umask(0)

  try:
    pid = os.fork()
    if pid > 0:
      # exit from second parent
      sys.exit(0)
  except OSError as err:
    sys.stderr.write('fork #2 failed: {0}\n'.format(err))
    sys.exit(1)

  # redirect standard file descriptors
  sys.stdout.flush()
  sys.stderr.flush()
  si = open(os.devnull, 'r')
  so = open(os.devnull, 'a+')
  se = open(os.devnull, 'a+')

  os.dup2(si.fileno(), sys.stdin.fileno())
  os.dup2(so.fileno(), sys.stdout.fileno())
  os.dup2(se.fileno(), sys.stderr.fileno())

  atexit.register(delpid)

  pid = str(os.getpid())
  with open(lockFileName,'w+') as f:
    f.write(pid + '\n')

  do_main_program()

