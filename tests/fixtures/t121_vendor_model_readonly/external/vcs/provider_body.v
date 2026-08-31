    wire [7:0] provider_hidden;
    assign provider_hidden = data_i ^ 8'h5a;
    assign data_o = provider_hidden;
