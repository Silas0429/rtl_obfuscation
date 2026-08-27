// Reproduces the StCache ECC-library pattern: a family of width variants that
// share port names, where a generate branch selects one and leaves the rest
// with no InstanceBodySymbol at all.  Every identifier in an unselected variant
// is unreachable by any semantic reference, so it is a preserve boundary rather
// than a missing binding rule.

module t109_ecc_dec_8 (input logic [7:0] data_i, output logic [3:0] syndrome_o);
    assign syndrome_o[0] = data_i[0] ^ data_i[1];
    assign syndrome_o[1] = data_i[2] ^ data_i[3];
    assign syndrome_o[2] = data_i[4] ^ data_i[5];
    assign syndrome_o[3] = data_i[6] ^ data_i[7];
endmodule

// Never elaborated: instantiated only from the untaken generate branch below.
// Note the port names are identical to the variant above, so the elaborated
// variant puts data_i and syndrome_o into the in-scope name set and these
// tokens would otherwise be charged against coverage.
module t109_ecc_dec_16 (input logic [15:0] data_i, output logic [3:0] syndrome_o);
    assign syndrome_o[0] = data_i[0]  ^ data_i[1]  ^ data_i[2]  ^ data_i[3];
    assign syndrome_o[1] = data_i[4]  ^ data_i[5]  ^ data_i[6]  ^ data_i[7];
    assign syndrome_o[2] = data_i[8]  ^ data_i[9]  ^ data_i[10] ^ data_i[11];
    assign syndrome_o[3] = data_i[12] ^ data_i[13] ^ data_i[14] ^ data_i[15];
endmodule

module t109_ecc_top #(parameter int WIDTH = 8) (
    input  logic [15:0] raw_data,
    output logic [3:0]  check
);
    if (WIDTH == 8) begin : g_narrow
        t109_ecc_dec_8 u_narrow (.data_i(raw_data[7:0]), .syndrome_o(check));
    end else begin : g_wide
        // Uninstantiated generate branch inside an elaborated module.
        t109_ecc_dec_16 u_wide (.data_i(raw_data), .syndrome_o(check));
    end
endmodule
