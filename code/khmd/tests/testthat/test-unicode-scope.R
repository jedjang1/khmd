test_that("escaped all-district scope keeps its original meaning", {
  a <- list(family="RENT",province="P",district="\uC804\uCCB4",
            date_from="2025-01-01",date_to="2025-12-31")
  b <- a; b$district <- "district"
  expect_true(khmd:::.khmd_overlap(a,b))
  expect_true(khmd:::.khmd_overlap(b,a))
  b$province <- "other"
  expect_false(khmd:::.khmd_overlap(a,b))
})
