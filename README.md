# billing.py

Works with Freeswitch and listens on events CHANNEL_BRIDGE and CHANNEL_UNBRIDGE and
calculates telephone fee based on minutes. It send SIP messages to a Patton media gateway
so it can send 16khz pulses to a pay phone. Events are logged to syslog.

This was a quick-and-dirty solution for a non-profit organization, so some
items are hard coded.

# Important Variables

* send_mail=1 # if you want to get e-mails
* smtp_from="sender@example.com"
* smtp_to="recipient@example.com"
* smtp_relay="localhost"
* aoc_amount="0.01" # payment unit = one 16khz pulse
* real_amount="0.05" # must match pay phone configuration
* ip = "192.168.106.3" # ip address of Patton media gateway
* host="127.0.0.1" # freeswitch server
* port="8021" # freeswitch port
* sip_from=="592" # SIP id of Patton
* function call: sendAOC("D",con,key,"192.168.106.7"... # IP address of Patton

Look out for regex with +49... which matches for numbers in
Germany. Outside Germany you probably want to change this.

# ESL

This is a library provided by Freeswitch

