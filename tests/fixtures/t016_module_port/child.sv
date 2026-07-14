module t016_child (
    input  logic [7:0] data_in,
    output logic [7:0] data_out
);
    logic [7:0] internal_wire;

    assign internal_wire = data_in;
    assign data_out = internal_wire;
endmodule
