#!/usr/bin/bash
# last 100 IDs, only one of each (use uniq), print out some python code to go into the test
# code will then probably be edited by hand to get into the test python (pending resolution of format issues)
# only execute on those lines for which $1 starts with HGNC
cut -f1,2  gene_ids.txt | uniq | tail -100 | awk -v SQ="'" '$1 ~ /^HGNC/ {print "mygids = compare_for_test(" SQ $2 SQ "," SQ $1 SQ",gids=mygids)" }' 
