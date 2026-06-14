# LLM Fault Location Prompt

Used for the auxiliary LLM localization baselines in RQ-2.

```text
Based on the following bug description, predict potential relevant code locations:
Description:
{{problem_statement}}
Please provide a JSON array containing the predicted locations where the bug fix is needed. Each location should include the full file path and the full function name.
The function field should be one of these formats:
- `package.module.Class.function_name` # For class's functions
- `package.module.function_name` # For standalone functions
- `package.module.Class.class_level_attribute` # For class-level attributes
- `package.module.MODULE_LEVEL_VALUE` # For module-level variables
Format:
[
    {
        "file_path": "package/submodule/file.py",
        "function": "package.module.Class.function_name"
    },
    {
        "file_path": "package/other/file.py",
        "function": "package.module.MODULE_LEVEL_VALUE"
    }
]
```
