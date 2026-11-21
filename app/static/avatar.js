// Profilbild: vor dem Hochladen im Browser quadratisch zuschneiden und verkleinern.
// So bleibt der Upload klein (Vercel erlaubt max. ~4.5 MB) und geht auch mit großen Handyfotos.
// Klappt das nicht (alter Browser), wird die Originaldatei geschickt - der Server verkleinert sowieso.
document.addEventListener("alpine:init", function () {
  Alpine.data("avatarUpload", function () {
    return {
      preview: null,
      busy: false,
      processing: false,
      async choose(event) {
        var input = event.target;
        var file = input.files && input.files[0];
        if (!file) { this.preview = null; return; }
        this.processing = true;
        try {
          var bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
          var side = Math.min(bitmap.width, bitmap.height);
          var canvas = document.createElement("canvas");
          canvas.width = canvas.height = 512;
          var ctx = canvas.getContext("2d");
          ctx.fillStyle = "#fff";
          ctx.fillRect(0, 0, 512, 512);
          ctx.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, 512, 512);
          var blob = await new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", 0.9); });
          if (blob && window.DataTransfer) {
            var dt = new DataTransfer();
            dt.items.add(new File([blob], "avatar.jpg", { type: "image/jpeg" }));
            input.files = dt.files;
          }
          this.preview = canvas.toDataURL("image/jpeg", 0.8);
        } catch (e) {
          this.preview = URL.createObjectURL(file);
        } finally {
          this.processing = false;
        }
      },
    };
  });
});
