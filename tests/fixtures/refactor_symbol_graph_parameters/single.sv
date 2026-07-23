module parameter_single #(
    parameter int WIDTH = 3
);
    localparam int LOCAL_WIDTH = WIDTH + 1;
    logic [LOCAL_WIDTH-1:0] payload;
endmodule
