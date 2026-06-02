# Parts Lists Present
> **Domain:** Spelling & Title Block | **Check key:** `parts_lists`

## Display Name

Parts Lists Present

## Pass

PASS — Einbauteilliste and Montageteilliste both present.

## Not Found

NOT FOUND — neither Einbauteilliste nor Montageteilliste visible on sheet.

## Description

Check that the Built-in Parts List and Mounting Parts List are provided.

## Reference Images

![Parts Lists Present example 1](./img_001.png)

## Check Prompt

CHECK — Parts Lists Present (parts_lists)
Verify the sheet contains both:
  • Einbauteilliste (embedded parts list)
  • Montageteilliste (assembly/mounting parts list)
Flag each table that is clearly absent.
If the sheet is too illegible to determine whether these tables are present, add "parts_lists" to not_found.
