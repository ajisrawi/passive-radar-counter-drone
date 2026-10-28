# Board C v4: design changes to finish routing.
#  - outer-layer GND pours are no longer trusted as planes: every GND pad fans out to an inner GND plane
#    (top pads: 0.25/0.1 microvia to In1, usually in the pad; bottom pads: microvia to In6)
#  - In4/In6 plane nets swapped (In4 = +1V0, In6 = GND) so bottom-side decoupling caps reach GND with microvias
#  - blind vias F.Cu-In2.Cu and In5.Cu-B.Cu shrunk 0.35/0.15 -> 0.25/0.1 stacked laser microvias
# Resumes the v3fix signal copper; plane-net fanouts are redone.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v4.sts
bestsave on $/board_c_v4_best.ses
read session $/board_c_v4_resume.ses
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
write session $/board_c_v4.ses
report status $/board_c_v4_status.txt
quit
