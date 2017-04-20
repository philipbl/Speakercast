var speakercastApp = angular.module('speakercastApp', []);

var first_presidency_names = ["Thomas S. Monson", "Henry B. Eyring", "Dieter F. Uchtdorf"];
var twelve_apostles_names = ["Russell M. Nelson", "Dallin H. Oaks", "M. Russell Ballard", "Robert D. Hales", "Jeffrey R. Holland", "David A. Bednar", "Quentin L. Cook", "D. Todd Christofferson", "Neil L. Andersen", "Ronald A. Rasband", "Gary E. Stevenson", "Dale G. Renlund"];

// var server_url = "http://127.0.0.1:5000";
var server_url = "http://speakercast.app.lundrigan.org";

speakercastApp.controller('SpeakerController', ['$scope', '$http', 'orderByFilter', function($scope, $http, orderBy) {
    $scope.first_presidency = [];
    $scope.twelve_apostles = [];
    var data;

    $http.get('assets/data.json').then(function(response) {
      data = response.data;
      $scope.first_presidency = [];
      $scope.twelve_apostles = [];

      angular.forEach(data, function(speaker) {
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

      $scope.propertyName = $scope.getLastName;
      $scope.speakers = orderBy(data, $scope.propertyName, false);

    });

    $scope.sortBy = function(propertyName, reverse) {
      $scope.propertyName = propertyName;
      $scope.speakers = orderBy(data, $scope.propertyName, reverse);
    };

    $scope.getLastName = function(user) {
      var name =  user.name.split(' ');
      return name[name.length - 1];
    }
}]);
