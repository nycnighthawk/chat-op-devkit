````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Stabilization: characterize, then fix the money bug
@@doc docs/PLAN.md
# Stabilization plan
| C1 | characterize load/total_value/restock | R3 |
| F1 | fix price parsing | R1 |
@@end
@@slices
[{"id":"C1","title":"characterize current behavior","acceptance":["R3"],"touches":["inventory.py"]},
 {"id":"F1","title":"fix price parsing","acceptance":["R1"],"touches":["inventory.py","tests/test_characterize.py"]}]
@@end
@@advance
<<<END>>>
````
