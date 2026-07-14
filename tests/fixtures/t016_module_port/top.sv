module t016_top (
    input  logic [7:0] data_in,
    output logic [7:0] data_out
);
    t016_child u_child (
        .data_in(data_in),
        .data_out(data_out)
    );
endmodule
