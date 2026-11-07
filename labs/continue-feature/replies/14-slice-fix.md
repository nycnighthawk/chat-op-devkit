The evidence shows the center marker was wrong (`:--:`). Fixing the root cause; the tests stay as they are.

````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Fix the center alignment marker
@@edit src/csv2md/convert.py
<<<<<<< SEARCH
_SEP = {"left": "---", "center": ":--:", "right": "---:"}
=======
_SEP = {"left": "---", "center": ":---:", "right": "---:"}
>>>>>>> REPLACE
@@end
<<<END>>>
````
