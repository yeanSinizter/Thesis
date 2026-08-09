import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

/** Positive control: SQL built from string concatenation (Semgrep formatted-sql-string). */
public class java_sql_concat {
    public static ResultSet unsafeLookup(Connection conn, String userId) throws SQLException {
        Statement st = conn.createStatement();
        return st.executeQuery("SELECT * FROM users WHERE id = " + userId);
    }
}
