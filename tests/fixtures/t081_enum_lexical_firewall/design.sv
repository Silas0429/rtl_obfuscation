module t081_child (
  input  logic data_i,
  output logic data_o
);
  typedef enum logic {
    MODE_SAFE,
    MODE_GAP
  } mode_e;
  parameter logic MODE = MODE_GAP;

  if (MODE == MODE_GAP) begin : g_gap
    assign data_o = 1'b0;
  end else begin : g_safe
    assign data_o = (MODE == MODE_SAFE) ? data_i : 1'b0;
  end
endmodule

module t081_top (
  input  logic data_i,
  output logic data_o
);
  t081_child #(.MODE(1'b0)) u_child (
    .data_i(data_i),
    .data_o(data_o)
  );
endmodule
