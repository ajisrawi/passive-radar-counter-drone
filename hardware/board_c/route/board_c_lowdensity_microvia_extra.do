# OpenRoute: 5 extra passes for the low-density microvia redesign of Board C, run only if passes 2-25 left it unfinished.
# Resumes from the final session of the main run and continues the cost table at row 26.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
status_file $/board_c_lowdensity_microvia_extra.sts
bestsave on $/board_c_lowdensity_microvia_extra_best.ses
read session $/board_c_lowdensity_microvia.ses
route 5 26
clean 1
write session $/board_c_lowdensity_microvia_extra.ses
report status $/board_c_lowdensity_microvia_extra_status.txt
report conflicts $/board_c_lowdensity_microvia_extra_drc.txt
quit
