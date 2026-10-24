"""
SQL Scripting - Starter Code

Implement `run_scripts(spark)`. Each numbered step is one spark.sql call:
1. WHILE script for the n-th Fibonacci number; n arrives as the parameter
   marker :n (args={"n": 10}); the script ends with SELECT a AS fib
2. Temporary SQL UDFs: scalar tier(balance DOUBLE) RETURNS STRING
   ('gold' >= 500, 'silver' >= 50, else 'basic') and table function
   accounts_above(min_balance DOUBLE) RETURNS TABLE (account STRING, balance DOUBLE)
3. FOR loop over accounts (ordered by account) collecting gold accounts
   into a space-separated string; end with SELECT trim(golds) AS golds
4. EXIT HANDLER FOR DIVIDE_BY_ZERO that selects 'fallback' AS outcome;
   the body divides sum(balance) by min(balance) as its own SELECT
5. Cursor over balances < 100 summing them (enable the two flags first)
6. SET PATH = system.session, system.builtin, spark_catalog.default,
   read current_path(), then SET PATH = DEFAULT_PATH
"""

from pyspark.sql import SparkSession


ACCOUNTS = [
    ("a1", 120.0), ("a2", 15.0), ("a3", 0.0), ("a4", 980.0), ("a5", 55.0),
]


def run_scripts(spark):
    """Run several SQL scripts and return their results."""

    spark.createDataFrame(ACCOUNTS, "account string, balance double") \
        .createOrReplaceTempView("accounts")

    # TODO 1: BEGIN DECLARE a, b, t BIGINT ...; WHILE i < :n DO ... END WHILE; SELECT a AS fib; END
    fib = None  # Replace with spark.sql(..., args={"n": 10}).first()["fib"]

    # TODO 2: CREATE OR REPLACE TEMPORARY FUNCTION tier(...) ... and accounts_above(...)
    tiers = None  # Replace: SELECT account, tier(balance) AS tier FROM accounts_above(10) ORDER BY account

    # TODO 3: FOR r AS SELECT account, balance FROM accounts ORDER BY account DO ... END FOR;
    gold_list = None  # Replace

    # TODO 4: DECLARE EXIT HANDLER FOR DIVIDE_BY_ZERO BEGIN SELECT 'fallback' AS outcome; END;
    handled = None  # Replace

    # TODO 5: enable spark.sql.scripting.cursorEnabled and
    #         spark.sql.scripting.continueHandlerEnabled, then
    #         DECLARE c CURSOR FOR ...; DECLARE CONTINUE HANDLER FOR NOT FOUND ...;
    #         OPEN / REPEAT FETCH ... UNTIL done END REPEAT / CLOSE; SELECT total;
    cursor_total = None  # Replace

    # TODO 6: enable spark.sql.path.enabled, SET PATH, read current_path(), reset
    path = None  # Replace

    return {
        "fib": fib,
        "tiers": tiers,
        "gold_list": gold_list,
        "handled": handled,
        "cursor_total": cursor_total,
        "path": path,
    }


# ---- Test harness (do not modify below this line) ----
if __name__ == "__main__":
    spark = (SparkSession.builder
        .appName("SqlScriptingTest")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate())

    result = run_scripts(spark)
    assert result is not None, "Function returned None"
    assert result["fib"] == 55, f"fib(10) should be 55, got {result['fib']}"
    tiers = {r["account"]: r["tier"] for r in result["tiers"].collect()}
    assert tiers == {"a1": "silver", "a2": "basic", "a4": "gold", "a5": "silver"}, tiers
    assert result["gold_list"] == "a4", f"Unexpected gold list: {result['gold_list']!r}"
    assert result["handled"] == "fallback", f"Handler should fire, got {result['handled']!r}"
    assert result["cursor_total"] == 70.0, f"Cursor total should be 70.0, got {result['cursor_total']}"
    assert result["path"] == "system.session,system.builtin,spark_catalog.default", result["path"]
    print("fib(10):", result["fib"])
    result["tiers"].show()
    print("gold:", result["gold_list"], "| handler:", result["handled"],
          "| cursor total:", result["cursor_total"])
    print("path:", result["path"])
    print("All tests passed!")
    spark.stop()
