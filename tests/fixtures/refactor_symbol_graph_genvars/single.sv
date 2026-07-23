module genvar_single;
    for (genvar only = 0; only < 1; only++) begin : g_only
        logic [only:0] lane_only;
    end
endmodule
