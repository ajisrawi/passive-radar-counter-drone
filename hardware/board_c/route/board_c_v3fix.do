# Board C: finish the last open connections of the v2 result.
# Resumes v2's copper (rip-up-able) on the DSN with corrected footprints; larger search budget plus the
# weighted-A* retry let the long JTAG/QSPI/ETH connections find their way; soft passes first so the opens can
# push neighbours aside, then hard passes to settle.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v3fix.sts
bestsave on $/board_c_v3fix_best.ses
read session $/board_c_lowdensity_microvia_v2.ses
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
write session $/board_c_v3fix.ses
report status $/board_c_v3fix_status.txt
quit
