"""Code editor widget — displays code preview, opens $EDITOR (nvim) for editing."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static, TextArea


# Minimal nvim config for PySpark editing with syntax highlighting + autocomplete
_NVIM_INIT = dedent("""\
    " SparkTutor nvim config — PySpark editing
    set nocompatible
    filetype plugin indent on
    syntax on

    " Python defaults
    set tabstop=4
    set shiftwidth=4
    set expandtab
    set smartindent
    set number
    set relativenumber
    set cursorline

    " Color scheme
    set termguicolors
    set background=dark
    colorscheme habamax

    " Built-in omni completion for Python
    set omnifunc=python3complete#Complete
    set completeopt=menuone,noinsert,noselect

    " Tab triggers completion menu
    inoremap <Tab> <C-n>
    inoremap <S-Tab> <C-p>

    " Auto-close brackets
    inoremap ( ()<Left>
    inoremap [ []<Left>
    inoremap { {}<Left>
    inoremap " ""<Left>
    inoremap ' ''<Left>

    " PySpark keyword completion via dictionary
    set complete+=k
    if filereadable(expand('~/.config/sparktutor/pyspark.dict'))
        execute 'set dictionary+=~/.config/sparktutor/pyspark.dict'
    endif

    " Status line shows file info
    set laststatus=2
    set statusline=%f\\ %m%r%h\\ [PySpark]\\ %=\\ Ln\\ %l,\\ Col\\ %c\\ \\ %p%%
""")

# PySpark keyword dictionary for autocomplete
_PYSPARK_DICT = dedent("""\
    SparkSession
    DataFrame
    Column
    Row
    StructType
    StructField
    StringType
    IntegerType
    LongType
    DoubleType
    FloatType
    BooleanType
    TimestampType
    DateType
    ArrayType
    MapType
    DecimalType
    BinaryType
    pyspark
    pyspark.sql
    pyspark.sql.functions
    pyspark.sql.types
    pyspark.sql.window
    pyspark.sql.streaming
    spark.builder
    spark.read
    spark.readStream
    spark.sql
    spark.table
    spark.createDataFrame
    spark.catalog
    spark.stop
    getOrCreate
    appName
    master
    config
    enableHiveSupport
    select
    filter
    where
    withColumn
    withColumnRenamed
    drop
    dropDuplicates
    distinct
    groupBy
    agg
    orderBy
    sort
    join
    union
    unionAll
    unionByName
    crossJoin
    limit
    head
    first
    collect
    take
    count
    show
    printSchema
    explain
    describe
    summary
    cache
    persist
    unpersist
    repartition
    coalesce
    write
    writeStream
    format
    mode
    option
    options
    save
    saveAsTable
    insertInto
    parquet
    json
    csv
    orc
    text
    jdbc
    partitionBy
    bucketBy
    sortBy
    trigger
    outputMode
    foreachBatch
    start
    awaitTermination
    col
    lit
    when
    otherwise
    isnull
    isnan
    isNotNull
    cast
    alias
    asc
    desc
    between
    isin
    like
    rlike
    startswith
    endswith
    contains
    substr
    trim
    ltrim
    rtrim
    lower
    upper
    length
    concat
    concat_ws
    split
    regexp_extract
    regexp_replace
    to_date
    to_timestamp
    date_format
    year
    month
    dayofmonth
    hour
    minute
    second
    current_date
    current_timestamp
    datediff
    date_add
    date_sub
    from_unixtime
    unix_timestamp
    window
    sum
    avg
    mean
    min
    max
    count
    countDistinct
    approx_count_distinct
    first
    last
    collect_list
    collect_set
    array_contains
    explode
    posexplode
    flatten
    array
    create_map
    map_keys
    map_values
    struct
    coalesce
    greatest
    least
    abs
    round
    ceil
    floor
    log
    log2
    log10
    pow
    sqrt
    exp
    row_number
    rank
    dense_rank
    percent_rank
    ntile
    lag
    lead
    cume_dist
    Window
    partitionBy
    orderBy
    rowsBetween
    rangeBetween
    unboundedPreceding
    unboundedFollowing
    currentRow
    udf
    pandas_udf
    broadcast
    monotonically_increasing_id
    spark_partition_id
    input_file_name
    transformWithState
    handleInputRows
    getValueState
    TimerValues
    StatefulProcessor
    StatefulProcessorHandle
    format_string
    from_json
    to_json
    schema_of_json
    from_csv
    schema_of_csv
    get_json_object
    json_tuple
    iceberg
    writeTo
    tableProperty
    using
    createOrReplace
    append
    overwritePartitions
""")


def _ensure_nvim_config() -> Path:
    """Write the SparkTutor nvim config and PySpark dictionary if missing."""
    config_dir = Path.home() / ".config" / "sparktutor"
    config_dir.mkdir(parents=True, exist_ok=True)

    init_path = config_dir / "init.vim"
    if not init_path.exists():
        init_path.write_text(_NVIM_INIT)

    dict_path = config_dir / "pyspark.dict"
    if not dict_path.exists():
        dict_path.write_text(_PYSPARK_DICT)

    return init_path


def _find_editor() -> list[str]:
    """Return the editor command to use, preferring nvim."""
    editor_env = os.environ.get("EDITOR", "")
    if editor_env:
        return editor_env.split()

    for candidate in ("nvim", "vim", "vi", "nano"):
        if shutil.which(candidate):
            return [candidate]

    return ["vi"]


class CodeEditor(Vertical):
    """PySpark code editor — shows preview in TUI, opens nvim for editing."""

    class CodeUpdated(Message):
        """Fired when the user saves and exits the editor."""
        def __init__(self, code: str) -> None:
            super().__init__()
            self.code = code

    def __init__(self, **kwargs) -> None:
        super().__init__(id="code-editor", **kwargs)
        self.border_title = "Code Editor"
        self._error_lines: set[int] = set()
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="sparktutor_"))

    def compose(self) -> ComposeResult:
        yield TextArea(
            "",
            language="python",
            theme="monokai",
            show_line_numbers=True,
            tab_behavior="indent",
            classes="code-editor-area",
            id="code-area",
        )
        yield Static(
            " [dim]Esc → controls → question | F5/F6/F7 jump zones[/]",
            id="editor-hint",
        )

    @property
    def text_area(self) -> TextArea:
        return self.query_one("#code-area", TextArea)

    @property
    def code(self) -> str:
        return self.text_area.text

    @code.setter
    def code(self, value: str) -> None:
        self.text_area.load_text(value)

    def set_starter_code(self, code: str) -> None:
        self.text_area.load_text(code)
        self._error_lines.clear()
        self.border_title = "Code Editor"

    def mark_error_lines(self, lines: set[int]) -> None:
        self._error_lines = lines
        if lines:
            self.border_title = f"Code Editor  [red]● {len(lines)} error(s)[/]"
        else:
            self.border_title = "Code Editor"

    def clear_errors(self) -> None:
        self._error_lines.clear()
        self.border_title = "Code Editor"

    def open_in_editor(self) -> None:
        """Suspend the TUI and open the code in $EDITOR (nvim by default)."""
        current_code = self.text_area.text
        tmp_file = self._tmp_dir / "exercise.py"
        tmp_file.write_text(current_code)

        editor_cmd = _find_editor()
        editor_name = Path(editor_cmd[0]).name

        # Build command with config for nvim/vim
        cmd = list(editor_cmd)
        if editor_name in ("nvim", "vim"):
            init_path = _ensure_nvim_config()
            cmd.extend(["-u", str(init_path)])

        cmd.append(str(tmp_file))

        # Suspend the Textual app, run editor in the raw terminal
        with self.app.suspend():
            subprocess.run(cmd, check=False)

        # Read back the edited code
        if tmp_file.exists():
            new_code = tmp_file.read_text()
            if new_code != current_code:
                self.text_area.load_text(new_code)
                self.post_message(self.CodeUpdated(new_code))
