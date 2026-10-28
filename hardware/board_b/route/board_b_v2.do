# Board B v2: the redesign's copper with SPI_CLK and the control nets boxing in ball U2-J5 ripped up; soft passes
# let them settle around each other, then hard passes.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_b_v2.sts
bestsave on $/board_b_v2_best.ses
read session $/board_b_v2_resume.ses
route 3 4
route 3 8
route 3 12
route 3 16
route 3 22
route 2 25
clean 1
miter
write session $/board_b_v2.ses
report status $/board_b_v2_status.txt
quit
