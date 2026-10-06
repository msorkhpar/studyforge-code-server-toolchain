#!/usr/bin/perl
# Apply a profile's `editor-extension` patches to files already in the image, refusing by name.
#
# usage: perl apply_patches.pl "<line>\n<line>..."
# A line is `file|sha256-before|sha256-after|old|new[|old|new...]`: the file must hash to
# `sha256-before` (else the extension is not the one the patch was written for and the build
# stops), every `old` must occur in it, each is replaced by `new` everywhere, and the result must
# hash to `sha256-after`. ⛔ No pattern: `old` is a literal string. Perl-base only (Digest::SHA).
use strict;
use warnings;
use Digest::SHA qw(sha256_hex);

sub slurp { my ($path) = @_; open(my $in, '<:raw', $path) or die "patch: cannot read $path: $!\n"; local $/; return scalar <$in>; }

for my $line (split /\n/, $ARGV[0] // '') {
    next unless length $line;
    my ($file, $before, $after, @pairs) = split /\|/, $line, -1;
    die "patch $file: a line is file|before|after|old|new...\n" if !@pairs || @pairs % 2;
    my $data = slurp($file);
    my $found = sha256_hex($data);
    die "patch $file: the file has sha256 $found, but the profile's patch is written for $before\n" if $found ne $before;
    while (@pairs) {
        my ($old, $new) = splice(@pairs, 0, 2);
        die "patch $file: the text '$old' does not occur in it\n" if index($data, $old) < 0;
        $data =~ s/\Q$old\E/$new/g;
    }
    my $result = sha256_hex($data);
    die "patch $file: the patched file has sha256 $result, but the profile pins $after\n" if $result ne $after;
    open(my $out, '>:raw', $file) or die "patch: cannot write $file: $!\n";
    print $out $data;
    close $out;
    print "patch $file: $before -> $after\n";
}
