`define GENVAR_REF(name) name

module macro_genvar_reference;
    genvar g;
    for (g = 0; `GENVAR_REF(g) < 1; g++) begin : g_macro_reference
        logic [g:0] lane_macro_reference;
    end
endmodule
