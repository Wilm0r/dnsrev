#!/usr/bin/python

import dns.reversename
import getopt
import ipaddr
import os
import re
import subprocess
import sys
import tempfile
import time

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


def dns_re(types):
	"""Simple DNS zonefile line matcher."""
	return re.compile(r"^([^\s]*\.)\s+(?:\d+\s+)?IN\s+(%s)\s+(.*)$" % "|".join(types))


def get_flag(flag):
	"""Ugly getopt wrapper."""
	flag = "-%s" % flag
	flags = getopt.getopt(sys.argv[1:], "dhns")[0]
	res = [y for x, y in flags if x == flag]
	if len(res) == 0:
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


if get_flag("h"):
	print """\
dnsrev - Autogen/refresh reverse DNS zonefiles.

Set your forward and reverse zones. All zonefiles have to exist already,
this script does not (yet) create reverse zonefiles from scratch, it only
updates them.

  -h    This help info.
  -n    Dry run.
  -d    Show diffs of changes.
  -s    Do not update SOA serial number."""
	
	sys.exit(1)


# Convert all config data into zonefile "objects".
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
		if ipaddr.IPNetwork(address) in f.sno:
			label = str(dns.reversename.from_address(address))
			if label in f.manual:
				#print "Already manually created: %s" % address
				pass # fuck you python
			elif label not in f.auto:
				f.auto[label] = name
			else:
				print "Duplicate entry, two names for %s" % address


# Generate the reverse files.
for f in rev_files:
	if f.auto:
		recs = []
		for ad in sorted(f.auto.keys()):
			recs.append("%-50s  IN PTR %s" % (ad, f.auto[ad]))
		
		if recs == f.oldauto:
			print "No changes for %s" % f.fn
		
		else:
			serial = new_soa(f.serial)
			print "Updating %s, new serial %d" % (f.fn, serial)
			
			head = f.head.rstrip()
			if not get_flag("s"):
				serre = re.compile(r"\b(SOA\b.*?)\b%d\b" % f.serial, re.S)
				head = serre.sub(r"\g<1>%d" % serial, head)
			
			fn_tmp = f.mktemp()
			o = file(fn_tmp, "w")
			o.write(head)
			o.write("\n\n%s\n\n%s\n" % (AUTO_SEP, "\n".join(recs)))
			o.close()
			
			p = subprocess.Popen(["/usr/bin/diff", "-u", f.fn, fn_tmp])
			p.communicate()
			
			if not get_flag("n"):
				os.rename(fn_tmp, f.fn)
			else:
				os.unlink(fn_tmp)
	
	else:
		# Bug: If the file had some autogen data we won't delete it. Oh well.
		print "No data for %s" % f.fn
		pass
