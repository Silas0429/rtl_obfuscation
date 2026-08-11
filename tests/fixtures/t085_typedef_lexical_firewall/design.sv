package t085_pkg;
  typedef enum logic {WordZero, WordOne} word_t;
endpackage

module t085_top (
  input  logic data_i,
  output logic data_o
);
  typedef enum logic {SafeZero, SafeOne} safe_t;
  safe_t safe_value;
`ifdef T085_TYPEDEF_QUERY
  import t085_pkg::*;
  word_t unsafe_value;
  logic [$bits(word_t)-1:0] width_probe;
  assign unsafe_value = data_i ? WordOne : WordZero;
  assign width_probe = data_i;
`endif
  assign safe_value = data_i ? SafeOne : SafeZero;
  assign data_o = (safe_value == SafeOne);
endmodule
