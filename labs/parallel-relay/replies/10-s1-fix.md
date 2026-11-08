````chatop
<<<CHATOP chat=@CHAT:S1@ turn=@TURN:S1@>>>
@@summary S1 fix: escape pipes (code only; RED was already proven)
@@edit src/csv2md/convert.py
<<<<<<< SEARCH
    return value.strip()
=======
    return value.replace("|", "\\|").strip()
>>>>>>> REPLACE
@@end
<<<END>>>
````
