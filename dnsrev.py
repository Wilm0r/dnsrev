#!/usr/bin/python
#
# dnsrev - Simple DNS PTR generator. Works with IPv4 and IPv6 addresses
# with different zonefile layouts.
#
# Copyright 2011-2016 Wilmer van der Gaast <wilmer@gaast.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

############################### DEPENDENCIES ###############################
# If it doesn't run properly, make sure you have the dnspython and ipaddr
# Python modules installed, and named-compilezones. On Debian systems, just
# apt-get install python3-dns bind9utils
#
# For Red Hat dependencies:
# dnf install python3-dns bind-utils

import dns.reversename
import getopt
import ipaddress
import os
import re
import subprocess
import sys
import tempfile
import time


AUTO_SEP = ";; ---- dnsrev.py ---- automatically generated, do not edit ---- dnsrev.py ----"


def subnet_rev(full_addr):
	"""Like dns.reversename.from_address but for subnets."""
	addr, mask = full_addr.split("/")
	full_label = str(dns.reversename.from_address(addr))
	if ':' in addr:
		rest = int((128 - int(mask)) / 4)
	else:
		rest = int((32 - int(mask)) / 8)
	return full_label.split(".", rest)[-1]


def parse_zone(fn, zone):
	"""Feed a zonefile through named-compilezone."""
	p = subprocess.Popen(["/usr/sbin/named-compilezone", "-o", "-", zone, fn],
	                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	zone, errors = p.communicate()
	if p.returncode > 0:
		print("While parsing %s:\n" % fn)
		print(errors)
		sys.exit(1)
	
	return (zone.decode("utf-8").splitlines())


def dns_re(types):
	"""Simple DNS zonefile line matcher."""
	return re.compile(r"^([^\s]*\.)\s+(?:\d+\s+)?IN\s+(%s)\s+(.*)$" % "|".join(types))


def get_flag(flag, default=None):
	"""Ugly getopt wrapper."""
	flag = "-%s" % flag
	flags = getopt.getopt(sys.argv[1:], "dhnsc:")[0]
	res = [y for x, y in flags if x == flag]
	if len(res) == 0:
		if default is not None:
			return default
		else:
			return False

	elif res[0] == "":
		return True
	else:
		return res[0]


def new_soa(old):
	"""Create new SOA for today's date (or increment the old one if
	otherwise the one would would be lower."""
	tm = time.localtime()
	new = (tm.tm_year * 1000000 +
	       tm.tm_mon  *   10000 +
	       tm.tm_mday *     100)
	if new > old:
		return new
	else:
		# Just +1 if necessary.
		return old + 1


# Using this more as a struct.
class ZoneFile(object):
	def __init__(self, fn):
		self.fn = fn

	def mktemp(self):
		dir, fn = os.path.split(self.fn)
		return tempfile.NamedTemporaryFile(dir=dir, prefix=(fn + ".")).name


cfg = {}
cfg_file = get_flag("c", "dnsrev.conf")

try:
	code = compile(open(cfg_file).read(), cfg_file, 'exec')
	exec(code, cfg)

except IOError:
	pass

if not cfg or get_flag("h"):
	print("""\
dnsrev - Autogen/refresh reverse DNS zonefiles.

Set your forward and reverse zones. All zonefiles have to exist already,
this script does not (yet) create reverse zonefiles from scratch, it only
updates them.

  -c [file]   Configuration file location (default: ./dnsrev.conf).
  -h          This help info.
  -n          Dry run.
  -d          Show diffs of changes.
  -s          Do not update SOA serial number.

The configuration file should define two lists of tuples like this:

FWD_ZONES = [("db.example.net", "example.net"),
             ...]
REV_ZONES = [("db.example.net.rev4", "192.0.32.0/24"),
             ("db.example.net.rev6", "2620:0:2d0:200::/64"),
             ...]

The first column is the name of the zonefile. The second column is the
domain name in FWD_ZONES, and the ASCII-formatted subnet (including
netmask) in REV_ZONES.

You can list as many forward and reverse zones as you want. There doesn't
have to be any kind of 1:1 relationship between any of them.""")
	
	sys.exit(1)


# Convert all config data into zonefile "objects".
rev_files = []
for zone in cfg["REV_ZONES"]:
	fn, sn = zone[0:2]
	o = ZoneFile(fn)
	o.sn = sn
	o.sno = ipaddress.ip_network(sn)
	if len(zone) > 2:
		o.zone = zone[2]
	else:
		o.zone = subnet_rev(sn)
	o.manual = {}
	o.auto = {}
	rev_files.append(o)

fwd_files = []
for fn, zone in cfg["FWD_ZONES"]:
	o = ZoneFile(fn)
	o.zone = zone
	fwd_files.append(o)


# Get all manually-set reverse info (and don't autogen that part).
revre = dns_re(["PTR", "SOA"])
for f in rev_files:
	cont = open(f.fn).read()
	parts = cont.split(AUTO_SEP)
	f.head = parts[0]
	f.oldauto = None
	if len(parts) > 1: # Better not be > 2 actually!
		f.oldauto = parts[1].strip().splitlines()
	
	fn_tmp = f.mktemp()
	open(fn_tmp, "w").write(f.head)
	for line in parse_zone(fn_tmp, f.zone):
		m = revre.match(line)
		if not m:
			continue
		mg = m.groups()
		
		if mg[1] == "PTR":
			label, _, name = m.groups()
			f.manual[label] = name
		else:
			soa = mg[2].split(" ")
			f.serial = int(soa[2])
	
	os.unlink(fn_tmp)


# Get all forward zone info.
fwd = []
for f in fwd_files:
	fwd += parse_zone(f.fn, f.zone)

addrs = []
addrre = dns_re(["A", "AAAA"])
for line in fwd:
	m = addrre.match(line)
	if not m:
		continue
	
	name, _, address = m.groups()
	for f in rev_files:
		if ipaddress.ip_network(address) in f.sno:
			if f.sno.ip.version == 4 and f.sno.prefixlen > 24:
				label = "%s.%s" % (address.split(".")[3], f.zone)
			else:
				label = str(dns.reversename.from_address(address))
			if label in f.manual:
				#print "Already manually created: %s" % address
				pass # fuck you python
			elif label not in f.auto:
				f.auto[label] = name
			else:
				print("Duplicate entry, two names for %s" % address)


# Generate the reverse files.
for f in rev_files:
	if f.auto:
		recs = []
		for ad in sorted(f.auto.keys()):
			recs.append("%-50s  IN PTR %s" % (ad, f.auto[ad]))
		
		if recs == f.oldauto:
			print("No changes for %s" % f.fn)
		
		else:
			serial = new_soa(f.serial)
			print("Updating %s, new serial %d" % (f.fn, serial))
			
			head = f.head.rstrip()
			if not get_flag("s"):
				serre = re.compile(r"\b(SOA\b.*?)\b%d\b" % f.serial, re.S)
				head = serre.sub(r"\g<1>%d" % serial, head)
			
			fn_tmp = f.mktemp()
			o = open(fn_tmp, "w")
			o.write(head)
			o.write("\n\n%s\n\n%s\n" % (AUTO_SEP, "\n".join(recs)))
			o.close()
			
			if get_flag("d"):
				p = subprocess.Popen(["/usr/bin/diff", "-u", f.fn, fn_tmp])
				p.communicate()
			
			if not get_flag("n"):
				os.rename(fn_tmp, f.fn)
			else:
				os.unlink(fn_tmp)
	
	else:
		# Bug: If the file had some autogen data we won't delete it. Oh well.
		print("No data for %s" % f.fn)
		pass
