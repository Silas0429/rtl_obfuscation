module genvar_unreachable;
    for (genvar k = 0; k < 1; k++) begin : g_hidden
        logic [k:0] lane_hidden;
    end
endmodule
