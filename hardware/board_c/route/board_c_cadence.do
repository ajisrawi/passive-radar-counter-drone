# Allegro PCB Router script for Board C: fan out, route, clean, save the session.
bestsave on board_c_cadence_best.w
fanout 5
route 25
clean 2
route 25 16
clean 2
write session board_c_cadence.ses
write wire board_c_cadence.w
report status board_c_cadence_status.txt
