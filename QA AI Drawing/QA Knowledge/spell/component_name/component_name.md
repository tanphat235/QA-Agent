# Component Name vs Title Block
> **Domain:** Spelling & Title Block | **Check key:** `component_name`

## Display Name

Component Name vs Title Block

## Pass

PASS — Wandansicht component name matches title block.

## Not Found

NOT FOUND — Wandansicht element label or title block name not visible.

## Description

Check whether the component name on the Wandansicht matches the drawing name in the title block.

## Reference Images

![Component Name vs Title Block example 1](./img_001.png)

## Check Prompt

CHECK — Component Name vs Title Block (component_name)
Verify the component/element name on the Wandansicht matches the drawing name in the title block.
Flag only where BOTH are visible and they clearly differ.

NOT FOUND conditions — add "component_name" to not_found (do NOT silently pass) if ANY of:
  • The Wandansicht view is not visible on the sheet
  • The component/element name label on the Wandansicht is not visible or not readable
  • The title block is not visible on the sheet
  • The drawing name field in the title block is not visible or not readable
