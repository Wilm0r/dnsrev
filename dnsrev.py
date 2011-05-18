#!/usr/bin/python

import dns.reversename
import ipaddr
import os
import re
import subprocess
import sys
import tempfile

os.chdir("test")

FWD_ZONES = [("db.beilen.gaast.net.int", "beilen.gaast.net"),
             ("db.dublin.gaast.net.int", "dublin.gaast.net"),
             ("db.co.gaast.net", "co.gaast.net"),
             ("db.gaast.net", "gaast.net")]
REV_ZONES = [("db.beilen.gaast.net.rev.0", "192.168.0.0/24"),
             ("db.beilen6.gaast.net.rev", "2001:888:174d::/48"),
             ("db.dublin.gaast.net.rev", "192.168.9.0/24"),
             ("db.dublin6.gaast.net.rev", "2001:770:17b::/48"),
             ("db.beilen.gaast.net.rev.168", "192.168.168.0/24"),
             ("db.co.gaast.net.rev", "192.168.78.0/24")]

AUTO_SEP = ";; ---- dnsrev.py ---- automatically generated, do not edit ---- dnsrev.py ----"


def subnet_rev(full_addr):
	"""Like dns.reversename.from_address but for subnets."""
	addr, mask = full_addr.split("/")
	full_label = str(dns.reversename.from_address(addr))
	if ':' in addr:
		rest = (128 - int(mask)) / 4
	else:
		rest = (32 - int(mask)) / 8
	return full_label.split(".", rest)[-1]


def parse_zone(fn, zone):
	"""Feed a zonefile through named-compilezone."""
	p = subprocess.Popen(["/usr/sbin/named-compilezone", "-o", "-", zone, fn],
	                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	zone, errors = p.communicate()
	if p.returncode > 0:
		print "While parsing %s:\n" % fn
		print errors
		sys.exit(1)
	
	return zone.splitlines()


# Using this more as a struct.
class ZoneFile(object):
	def __init__(self, fn):
		self.fn = fn

rev_files = []
for fn, sn in REV_ZONES:
	o = ZoneFile(fn)
	o.sn = sn
	o.sno = ipaddr.IPNetwork(sn)
	o.zone = subnet_rev(sn)
	o.manual = {}
	o.auto = {}
	rev_files.append(o)

fwd_files = []
for fn, zone in FWD_ZONES:
	o = ZoneFile(fn)
	o.zone = zone
	fwd_files.append(o)


# Get all manually-set reverse info (and don't autogen that part).
revre = re.compile(r"^([^\s]*\.)\s+\d+\s+IN\s+(PTR)\s+(.*)$")
for f in rev_files:
	cont = open(f.fn).read()
	f.head = cont.split(AUTO_SEP)[0]
	
	fn_tmp = f.fn + ".dnspy.tmp"
	open(fn_tmp, "w").write(f.head)
	for line in parse_zone(fn_tmp, f.zone):
		m = revre.match(line)
		if m:
			label, _, name = m.groups()
			f.manual[label] = name
	
	os.unlink(fn_tmp)


# Get all forward zone info.
fwd = []
for f in fwd_files:
	fwd += parse_zone(f.fn, f.zone)

addrs = []
addrre = re.compile(r"^([^\s]*\.)\s+\d+\s+IN\s+(A|AAAA)\s+(.*)$")
for line in fwd:
	m = addrre.match(line)
	if not m:
		continue
	
	name, _, address = m.groups()
	for f in rev_files:
		if ipaddr.IPNetwork(address) in f.sno:
			label = str(dns.reversename.from_address(address))
			if label in f.manual:
				#print "Already manually created: %s" % address
				pass # fuck you python
			elif label not in f.auto:
				f.auto[label] = name
			else:
				print "Duplicate entry, two names for %s" % address


for f in rev_files:
	if f.auto:
		fn_tmp = f.fn + ".dnspy.tmp"
		o = file(fn_tmp, "w")
		o.write(f.head)
		o.write(AUTO_SEP + "\n\n")
		for ad in sorted(f.auto.keys()):
			o.write("%-50s  IN PTR %s\n" % (ad, f.auto[ad]))
