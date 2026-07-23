module parameter_shadow #(
    parameter int WIDTH = 5
);
    if (1) begin : g_shadow
        localparam int WIDTH = 2;
        logic [WIDTH-1:0] shadowed;
    end
    logic [WIDTH-1:0] outer_value;
endmodule
