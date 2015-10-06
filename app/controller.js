var speakercastApp = angular.module('speakercastApp', []);

var first_presidency_names = ["Thomas S. Monson", "Henry B. Eyring", "Dieter F. Uchtdorf"];
var twelve_apostles_names = ["Russell M. Nelson", "Dallin H. Oaks", "M. Russell Ballard", "Richard G. Scott", "Robert D. Hales", "Jeffrey R. Holland", "David A. Bednar", "Quentin L. Cook", "D. Todd Christofferson", "Neil L. Andersen"];

// var server_url = "http://127.0.0.1:5000";
var server_url = "http://speakercast.app.lundrigan.org";

speakercastApp.controller('SpeakerController', function($scope, $http) {
    $http.get(server_url + '/speakers').then(function(response) {
      $scope.speakers = response.data;
      $scope.first_presidency = [];
      $scope.twelve_apostles = [];

      angular.forEach($scope.speakers, function(speaker) {
        var first_presidency_index = first_presidency_names.indexOf(speaker.name);
        var twelve_apostles_index = twelve_apostles_names.indexOf(speaker.name);

        if (first_presidency_index >= 0) {
          speaker.index = first_presidency_index;
          $scope.first_presidency.push(speaker);
        }
        else if (twelve_apostles_index>= 0) {
          speaker.index = twelve_apostles_index;
          $scope.twelve_apostles.push(speaker);
        }
      });
    });

    $scope.anySelected = false;

    $scope.selected = function() {
      var names = [];
      angular.forEach($scope.speakers, function(speaker) {
        if(speaker.selected) {
          names.push(speaker);
        }
      });

      $scope.anySelected = names.length > 0;

      return names;
    };

    $scope.generate = function() {
      var selected = $scope.selected();

      // Only keep the name of the speaker
      var selected_names = []
      angular.forEach(selected, function(speaker) {
        selected_names.push(speaker.name);
      });

      $http({
        method: 'POST',
        url: server_url + "/generate",
        data: {'speakers': selected_names}
      }).then(function (response) {
        var id = response.data;
        $scope.feedUrl = server_url + "/feed/" + id;
      });
    };
});

speakercastApp.directive('myRepeatDirective', function() {
  return function(scope, element, attrs) {
    if (scope.$last) {
      console.log("before: " + $(document).height());
      setTimeout(set_affix, 1000);
    }
  };
});
