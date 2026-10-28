# OpenRoute v6 for Board C: original placement, resumed from the v3 checkpoint, with blind and buried via spans
# so BGA escapes stop blocking all four signal layers with 0.45 mm through vias.
#   blind  F.Cu..In2.Cu  0.30/0.15 mm   (outer signal to first inner signal, passes the In1 GND plane)
#   buried In2.Cu..In5.Cu 0.45/0.20 mm  (inner signal pair, passes the In3/In4 planes)
#   blind  In5.Cu..B.Cu  0.30/0.15 mm   (second inner signal to bottom, passes the In6 +1V0 plane)
# The through via Via[0-7]_450:200_um stays available for plane fanout and long layer changes.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
define via 0.30 0.15 F.Cu In2.Cu
define via 0.45 0.20 In2.Cu In5.Cu
define via 0.30 0.15 In5.Cu B.Cu
status_file $/board_c_v6_microvia.sts
bestsave on $/board_c_v6_microvia_best.ses
read session $/board_c_v3_best.ses
route 3 7
route 3 10
route 3 13
route 3 16
route 3 19
route 3 22
route 3 25
clean 1
write session $/board_c_v6_microvia.ses
report status $/board_c_v6_microvia_status.txt
report conflicts $/board_c_v6_microvia_drc.txt
quit
