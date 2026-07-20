module lowrisk_top (
    input  logic       clk,
    input  logic [3:0] data_i,
    output logic [3:0] data_o
);
    lowrisk_child u_child (
        .clk(clk),
        .data_i(data_i),
        .data_o(data_o)
    );
endmodule
