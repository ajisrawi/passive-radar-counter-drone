# Board B redesign: RF backbone kept (SMAs, baluns, AD9361s, FMC, holes), everything else autoplaced with
# decoupling affinity and RF/clock net weights; HDI via spans as on board C (stacked laser microvias, buried
# In2-In5); outer-layer GND pours are not planes, so every GND pad fans out to In1/In3/In6.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_b_redesign.sts
bestsave on $/board_b_redesign_best.ses
route 3 1
route 3 4
route 3 7
route 3 10
route 3 13
route 3 16
route 3 19
route 3 22
route 2 25
clean 1
miter
write session $/board_b_redesign.ses
report status $/board_b_redesign_status.txt
quit
