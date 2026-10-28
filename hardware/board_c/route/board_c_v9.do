# Board C v9: v8 with JTAG_TDI ripped up (its escape fenced in the +1V0 ball U1-G7); G7 fans out first, then JTAG_TDI reroutes.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v9.sts
bestsave on $/board_c_v9_best.ses
read session $/board_c_v9_resume.ses
route 3 6
route 3 12
route 3 16
route 2 22
route 2 25
clean 1
miter
write session $/board_c_v9.ses
report status $/board_c_v9_status.txt
quit
