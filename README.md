# dnsrev - Autogen/refresh reverse DNS zonefiles.

This is a simple but effective DNS reverse/PTR zonefile generator.
Features:

 * Supports multiple zonefiles, both forward and reverse, that may or
   may not have any 1:1 mapping between them. I.e. just throw it all
   your forward and reverse zonefiles, tell it which file contains PTRs
   for which IPv4 or IPv6 prefix and the script will do the rest.
 * Preserves existing manual PTR records (also helps in case of multiple
   names pointing at the same IP address).
 * Passes your zonefiles through named-compilezone for normalisation and
   interpretation of stuff like $GENERATE.

## Dependencies

It uses the `dnspython` and `ipaddr` Python modules, and
`named-compilezones`. On Debian-like systems, just run:

```
apt-get install python-ipaddr python-dnspython bind9utils
```

## Usage

Just update `dnsrev.conf` with all your zonefiles and run `dnsrev.py`.
The script will try to keep all auto-generated changes in a separate
section at the bottom of your reverse files, it will not delete or
modify anything outside that section (other than the SOA serial# which
it will update, using the usual YYYYMMDDXX scheme).

## --help

```
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
have to be any kind of 1:1 relationship between any of them.
```
