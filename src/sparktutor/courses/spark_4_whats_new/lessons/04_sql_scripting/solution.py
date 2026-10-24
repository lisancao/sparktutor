"""
SQL Scripting - Solution

Procedural SQL: variables, loops, handlers, SQL UDFs, cursors and PATH.
"""

from pyspark.sql import SparkSession


ACCOUNTS = [
    ("a1", 120.0), ("a2", 15.0), ("a3", 0.0), ("a4", 980.0), ("a5", 55.0),
]


def run_scripts(spark):
    """Run several SQL scripts and return their results."""

    spark.createDataFrame(ACCOUNTS, "account string, balance double") \
        .createOrReplaceTempView("accounts")

    # 1. WHILE loop with local variables. A script returns the result of
    #    the last statement that produced one.
    fib = spark.sql("""
        BEGIN
          DECLARE a BIGINT DEFAULT 0;
          DECLARE b BIGINT DEFAULT 1;
          DECLARE t BIGINT;
          DECLARE i INT DEFAULT 0;
          WHILE i < :n DO
            SET t = a + b;
            SET a = b;
            SET b = t;
            SET i = i + 1;
          END WHILE;
          SELECT a AS fib;
        END
    """, args={"n": 10}).first()["fib"]

    # 2. SQL UDFs (4.0): a scalar function and a table function.
    spark.sql("""
        CREATE OR REPLACE TEMPORARY FUNCTION tier(balance DOUBLE)
        RETURNS STRING
        RETURN CASE WHEN balance >= 500 THEN 'gold'
                    WHEN balance >= 50 THEN 'silver'
                    ELSE 'basic' END
    """)
    spark.sql("""
        CREATE OR REPLACE TEMPORARY FUNCTION accounts_above(min_balance DOUBLE)
        RETURNS TABLE (account STRING, balance DOUBLE)
        RETURN SELECT account, balance FROM accounts WHERE balance > min_balance
    """)
    tiers = spark.sql("""
        SELECT account, tier(balance) AS tier FROM accounts_above(10) ORDER BY account
    """)

    # 3. FOR loop over a query plus IF, accumulating into a variable.
    gold_list = spark.sql("""
        BEGIN
          DECLARE golds STRING DEFAULT '';
          FOR r AS SELECT account, balance FROM accounts ORDER BY account DO
            IF tier(r.balance) = 'gold' THEN
              SET golds = golds || r.account || ' ';
            END IF;
          END FOR;
          SELECT trim(golds) AS golds;
        END
    """).first()["golds"]

    # 4. EXIT handler: catch DIVIDE_BY_ZERO and return a fallback. The risky
    #    query is a statement of its own: in 4.2.0 an error raised inside a
    #    scalar subquery of SET is not matched by handlers.
    handled = spark.sql("""
        BEGIN
          DECLARE EXIT HANDLER FOR DIVIDE_BY_ZERO
            BEGIN
              SELECT 'fallback' AS outcome;
            END;
          SELECT CAST(sum(balance) / min(balance) AS STRING) AS outcome FROM accounts;
        END
    """).first()["outcome"]

    # 5. Cursors (4.2). Off by default behind internal flags; CONTINUE
    #    handlers (needed for NOT FOUND) are flag-gated too.
    spark.conf.set("spark.sql.scripting.cursorEnabled", "true")
    spark.conf.set("spark.sql.scripting.continueHandlerEnabled", "true")
    cursor_total = spark.sql("""
        BEGIN
          DECLARE bal DOUBLE;
          DECLARE done BOOLEAN DEFAULT false;
          DECLARE total DOUBLE DEFAULT 0;
          DECLARE c CURSOR FOR SELECT balance FROM accounts WHERE balance < 100;
          DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = true;
          OPEN c;
          REPEAT
            FETCH c INTO bal;
            IF NOT done THEN
              SET total = total + bal;
            END IF;
          UNTIL done END REPEAT;
          CLOSE c;
          SELECT total;
        END
    """).first()["total"]

    # 6. SQL PATH (4.2): also behind a flag; current_path() always works.
    spark.conf.set("spark.sql.path.enabled", "true")
    spark.sql("SET PATH = system.session, system.builtin, spark_catalog.default")
    path = spark.sql("SELECT current_path() AS p").first()["p"]
    spark.sql("SET PATH = DEFAULT_PATH")

    return {
        "fib": fib,
        "tiers": tiers,
        "gold_list": gold_list,
        "handled": handled,
        "cursor_total": cursor_total,
        "path": path,
    }


# ---- Test harness ----
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
