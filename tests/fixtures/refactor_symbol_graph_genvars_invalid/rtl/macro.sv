`define DECLARE_GENVAR(name) genvar name

module macro_genvar;
    `DECLARE_GENVAR(g);
    for (g = 0; g < 1; g++) begin : g_macro
        logic [g:0] lane_macro;
    end
endmodule
